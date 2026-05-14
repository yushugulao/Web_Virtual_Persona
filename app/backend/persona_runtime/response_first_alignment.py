"""Response-first route for open persona turns.

This route drafts a short natural reply before retrieval, then uses that draft only
as a retrieval hint and tone seed. It must never become an independent fact source.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.backend.persona_runtime.evidence_policy import REFLECTIVE_KEYWORDS, VOICE_STYLE_KEYWORDS
from app.backend.schemas.chat import ChatRequest
from app.backend.services.conversation_memory import (
    ConversationTurn,
    SessionContextBundle,
    format_conversation_context,
    format_session_context_bundle,
    trim_text,
)
from app.backend.services.dialogue_policy import (
    is_historical_persona_id,
    should_skip_retrieval_for_ordinary_query,
)
from app.backend.services.model_diagnostics import model_diagnostic_phase
from app.backend.services.model_service import LocalModelClient
from app.backend.services.persona_service import get_persona, normalize_persona_id
from app.backend.services.persona_voice_service import format_persona_voice_style_for_prompt


BLOCKED_RESPONSE_FIRST_KEYWORDS = (
    "prompt",
    "系统提示",
    "密码",
    "手机号",
    "身份证",
    "现代",
    "手机",
    "马斯克",
    "可莉",
    "结婚",
    "你是不是",
    "你是",
    "1+1",
    "翻译",
    "改写",
)


@dataclass(frozen=True)
class ResponseFirstPlan:
    enabled: bool
    reason: str


def build_response_first_plan(
    *,
    request: ChatRequest,
    persona_id: str,
    skip_retrieval: bool,
) -> ResponseFirstPlan:
    effective_persona_id = normalize_persona_id(persona_id)
    query = request.message
    normalized = query.lower()
    if skip_retrieval:
        return ResponseFirstPlan(False, "ordinary_or_no_retrieval_route")
    if not is_historical_persona_id(effective_persona_id):
        return ResponseFirstPlan(False, "non_historical_persona")
    if should_skip_retrieval_for_ordinary_query(query, effective_persona_id):
        return ResponseFirstPlan(False, "ordinary_task")
    if any(keyword in normalized or keyword in query for keyword in BLOCKED_RESPONSE_FIRST_KEYWORDS):
        return ResponseFirstPlan(False, "boundary_or_task_sensitive")
    if any(keyword in normalized for keyword in VOICE_STYLE_KEYWORDS):
        return ResponseFirstPlan(True, "voice_style_open_turn")
    if any(keyword in normalized for keyword in REFLECTIVE_KEYWORDS):
        return ResponseFirstPlan(True, "reflective_open_turn")
    if len(query) >= 8 and any(keyword in query for keyword in ("聊", "谈谈", "觉得", "看待")):
        return ResponseFirstPlan(True, "open_chitchat_turn")
    return ResponseFirstPlan(False, "not_response_first_candidate")


def build_response_first_draft_prompt(
    *,
    request: ChatRequest,
    persona_id: str,
    conversation_turns: list[ConversationTurn],
    session_context_bundle: SessionContextBundle | None = None,
) -> str:
    effective_persona_id = normalize_persona_id(persona_id)
    persona = get_persona(effective_persona_id)
    voice_style = format_persona_voice_style_for_prompt(effective_persona_id)
    history = format_session_context_bundle(session_context_bundle) or format_conversation_context(
        conversation_turns[-4:]
    )
    return f"""你现在要先写一个很短的自然回应草稿，后续系统会再检索档案并重写。
说话者：{persona.name}
规则：
- 只写自然草稿，不写分析过程。
- 不新增未支持的传记事实、时代知识、现代类比、私人经历或实时状态；若后续检索或用户本轮提供了可追溯信息，可在重写阶段使用。
- 如果问题需要事实支撑，只写语气和互动方向，不下事实结论。
- 草稿最多 3 句，语气要像真人即时回答，不要模板化拒答。

最近对话：
{history or "（无）"}

人物声音参考：
{voice_style or "（无）"}

用户问题：
{request.message}

自然草稿：
"""


def build_response_first_retrieval_query(query: str, draft: str) -> str:
    if not draft.strip():
        return query
    return (
        f"{query}\n\n"
        "Response-first draft retrieval hint, not a fact source:\n"
        f"{trim_text(draft, 240)}"
    )


def format_response_first_prompt_context(draft: str) -> str:
    if not draft.strip():
        return ""
    return (
        "Response-first 自然草稿（只作为语气起点，不是事实来源；必须用档案证据重写）：\n"
        f"{trim_text(draft, 360)}\n"
    )


def build_response_first_trace_note(plan: ResponseFirstPlan, draft: str | None) -> str:
    if not plan.enabled or not draft:
        return f"Response-first Persona Route: skipped ({plan.reason})."
    return (
        "Response-first Persona Route: "
        f"enabled ({plan.reason}); natural draft generated before retrieval and used only as a hint."
    )


async def generate_response_first_draft(
    *,
    client: LocalModelClient,
    request: ChatRequest,
    persona_id: str,
    conversation_turns: list[ConversationTurn],
    timeout_seconds: float,
    num_predict: int,
    model_name: str,
    session_context_bundle: SessionContextBundle | None = None,
) -> tuple[str | None, str | None]:
    prompt = build_response_first_draft_prompt(
        request=request,
        persona_id=persona_id,
        conversation_turns=conversation_turns,
        session_context_bundle=session_context_bundle,
    )
    try:
        with model_diagnostic_phase("response_first_draft"):
            draft, model = await client.generate(
                prompt,
                timeout_seconds=max(10.0, min(timeout_seconds, 45.0)),
                num_predict=max(128, min(num_predict, 320)),
                model_name=model_name,
                think=False,
            )
    except Exception:
        return None, None
    if model == "fallback":
        return None, model
    cleaned = client._clean_response(draft).strip()
    if not cleaned:
        return None, model
    return trim_text(cleaned, 360), model
