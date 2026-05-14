from __future__ import annotations

import re

from app.rag.chunking.markdown import Chunk
from app.rag.retrieval.local_reranker import matching_rules


CONTENT_RE = re.compile(r"[\w\u4e00-\u9fff]", re.UNICODE)
MIN_INTENT_WEIGHT = 0.05
RELATIVE_INTENT_THRESHOLD = 0.45

SOURCE_TYPE_TRACE_LABELS = {
    "profile": "人物档案",
    "reviewed_profile": "人物档案",
    "resume": "简历",
    "project": "项目档案",
    "timeline": "时间线",
    "values": "价值观",
    "thinking_style": "思考方式",
    "colleague": "同事视角",
    "qa_seed": "问答种子",
    "evidence_cards": "证据卡",
    "evidence_expansion": "场景扩展",
    "negative_fact": "边界记录",
    "safety_policy": "谈话边界",
}


SELECTOR_RULES: tuple[tuple[tuple[str, ...], dict[str, float]], ...] = (
    (
        ("开始写代码", "写代码前", "同学", "队友"),
        {"colleague": 0.56, "thinking_style": 0.10},
    ),
    (
        ("事实优先的价值观", "降低语气强度", "回答语气"),
        {"values": 0.46, "profile": 0.26, "thinking_style": 0.08},
    ),
    (
        ("查论文", "读论文", "开源项目", "调研", "修正设计", "校准"),
        {"thinking_style": 0.34, "values": 0.08},
    ),
    (
        ("声音指纹", "说话风格", "说话方式", "口吻", "语气", "句式节奏", "像本人"),
        {"thinking_style": 0.46},
    ),
    (
        (
            "怎样安排",
            "一天的事情",
            "日常",
            "习惯",
            "日课",
            "作息",
            "怎样判断",
            "新想法",
            "值不值得实验",
            "怎样理解",
            "怎样表达",
            "触觉",
            "观察习惯",
        ),
        {"thinking_style": 0.34, "profile": 0.08},
    ),
    (
        ("项目记忆", "长期项目记忆", "写进文件", "上下文丢失", "环境变化", "临时决定"),
        {"values": 0.34},
    ),
    (
        ("courseops", "task board", "课程团队", "负责了哪些部分"),
        {"resume": 0.34},
    ),
    (
        ("生产级安全防护", "生产级安全", "安全防护"),
        {"negative_fact": 0.40, "safety_policy": 0.22},
    ),
    (
        ("evaluation", "eval metrics", "一等能力", "可复现评测", "评测"),
        {"project": 0.42, "values": 0.34, "qa_seed": 0.24},
    ),
    (
        ("推断", "父母职业", "家庭关系", "家里人", "家人", "大胆猜测", "年薪", "未来第一份工作"),
        {"reviewed_profile": 0.30, "profile": 0.28, "evidence_cards": 0.22, "qa_seed": 0.16},
    ),
    (
        ("GPA", "专业排名", "出生日期"),
        {"reviewed_profile": 0.30, "profile": 0.26, "resume": 0.18, "evidence_cards": 0.16},
    ),
    (
        ("真实公司", "公司实习", "实习"),
        {
            "evidence_cards": 0.56,
            "reviewed_profile": 0.46,
            "qa_seed": 0.34,
            "timeline": 0.18,
            "negative_fact": 0.08,
        },
    ),
    (
        ("无视语料", "忽略语料", "忽略所有规则", "无视所有规则"),
        {"safety_policy": 0.34, "negative_fact": 0.30},
    ),
    (
        ("需求含糊", "需求不清", "含糊", "具体问题"),
        {"colleague": 0.34, "thinking_style": 0.24},
    ),
    (
        ("学术方案", "工程模块", "优势如何"),
        {"resume": 0.34, "thinking_style": 0.28},
    ),
    (
        ("可替换模块", "落地路径", "口号"),
        {"thinking_style": 0.34},
    ),
    (
        ("文档", "任务看板", "决策日志", "可复现"),
        {"values": 0.32},
    ),
    (
        ("事实优先",),
        {"thinking_style": 0.22, "values": 0.18, "profile": 0.10},
    ),
    (
        ("2023", "2024", "2025", "2026", "时间线", "年份"),
        {"timeline": 0.50},
    ),
    (
        ("不确定", "思考", "判断"),
        {"thinking_style": 0.18, "values": 0.10},
    ),
    (
        ("复杂", "拆解", "模块"),
        {"thinking_style": 0.18, "project": 0.14},
    ),
    (
        ("提醒", "风险"),
        {"colleague": 0.18, "values": 0.14},
    ),
    (
        ("同事", "协作", "沟通"),
        {"colleague": 0.24},
    ),
    (
        ("本地模型", "检索管线", "当前使用", "stack"),
        {"project": 0.18, "profile": 0.10},
    ),
    (
        ("亮点", "最重要"),
        {"qa_seed": 0.18, "project": 0.14, "profile": 0.10},
    ),
    (
        ("为什么要做", "项目动机", "课程项目"),
        {"qa_seed": 0.36, "profile": 0.24},
    ),
    (
        ("后续", "最应该升级", "升级哪些", "路线", "roadmap"),
        {"project": 0.46, "values": 0.26},
    ),
    (
        ("手机号", "联系方式", "电话"),
        {"reviewed_profile": 0.26, "profile": 0.20, "evidence_cards": 0.14},
    ),
    (
        ("家庭住址", "住址", "身份证", "隐私信息", "敏感"),
        {"reviewed_profile": 0.22, "profile": 0.18, "evidence_cards": 0.12},
    ),
    (
        (
            "医疗",
            "心理",
            "心理咨询",
            "特殊教育",
            "诊断",
            "专业建议",
            "治疗",
            "medical",
            "psychological",
            "diagnosis",
            "treatment",
            "special education",
            "special-education",
            "clinical",
        ),
        {"negative_fact": 0.34, "profile": 0.10},
    ),
    (
        ("银行卡", "账号密码", "账号", "密码"),
        {"safety_policy": 0.18, "negative_fact": 0.16},
    ),
    (
        ("system prompt", "chain-of-thought", "隐藏推理", "泄露"),
        {"safety_policy": 0.32},
    ),
    (
        ("忽略", "所有规则", "所有证据", "刚刚告诉你", "当作事实", "写进回答"),
        {"safety_policy": 0.20, "negative_fact": 0.18},
    ),
    (
        ("顶会", "顶会论文", "发表论文", "发表过论文", "高级工程师", "真实企业"),
        {"reviewed_profile": 0.24, "profile": 0.20, "evidence_cards": 0.18, "qa_seed": 0.12},
    ),
    (
        ("没有完成", "未完成", "当前限制", "已经完成", "长期记忆", "reranker", "PDF 多模态", "自动化资料转 Markdown", "Docling", "MinerU", "生产级安全"),
        {"negative_fact": 0.40, "project": 0.24},
    ),
    (
        ("国家级", "竞赛奖项", "奖项"),
        {
            "evidence_cards": 0.44,
            "reviewed_profile": 0.34,
            "qa_seed": 0.24,
            "negative_fact": 0.10,
        },
    ),
)


def select_sources(
    results: list[tuple[Chunk, float]],
    *,
    max_results: int,
    min_results: int = 1,
    query: str | None = None,
    intent_filter_enabled: bool = True,
) -> tuple[list[tuple[Chunk, float]], str]:
    if not results or max_results <= 0:
        return [], "片段选择没有找到候选。"

    informative = [item for item in results if is_informative_chunk(item[0])]
    pool = informative or results
    weights = intent_source_weights(query) if intent_filter_enabled and query else {}
    target_sources = target_source_types(weights)
    intent_selected = (
        select_intent_candidates(pool, weights, target_sources, max_results=max_results)
        if target_sources
        else []
    )
    selected = intent_selected or pool[:max_results]

    if len(selected) < min_results:
        selected = results[:min_results]

    dropped_short = len(results) - len(informative) if informative else 0
    dropped_tail = max(0, len(pool) - len(selected))
    intent_note = ""
    if intent_selected:
        intent_note = (
            " 意图过滤目标："
            f"{format_source_types(target_sources, weights)}。"
        )
    note = (
        f"片段选择保留 {len(selected)}/{len(results)} 个融合候选"
        f"（上限={max_results}，短片段丢弃={dropped_short}，尾部丢弃={dropped_tail}）。"
        f"{intent_note}"
    )
    return selected, note


def is_informative_chunk(chunk: Chunk, min_content_chars: int = 24) -> bool:
    content_chars = CONTENT_RE.findall(chunk.text)
    if len(content_chars) < min_content_chars:
        return False
    stripped = chunk.text.strip()
    return not stripped.startswith("# ") or "\n" in stripped


def intent_source_weights(query: str | None) -> dict[str, float]:
    if not query:
        return {}

    weights: dict[str, float] = {}
    for rule in matching_rules(query):
        merge_weights(weights, rule.source_weights)

    normalized = query.lower()
    for triggers, source_weights in SELECTOR_RULES:
        if any(trigger.lower() in normalized for trigger in triggers):
            merge_weights(weights, source_weights)
    return weights


def merge_weights(target: dict[str, float], updates: dict[str, float]) -> None:
    for source_type, weight in updates.items():
        target[source_type] = max(target.get(source_type, 0.0), weight)


def target_source_types(weights: dict[str, float]) -> set[str]:
    if not weights:
        return set()
    max_weight = max(weights.values())
    threshold = max(MIN_INTENT_WEIGHT, max_weight * RELATIVE_INTENT_THRESHOLD)
    return {
        source_type
        for source_type, weight in weights.items()
        if weight + 1e-9 >= threshold
    }


def select_intent_candidates(
    pool: list[tuple[Chunk, float]],
    weights: dict[str, float],
    target_sources: set[str],
    *,
    max_results: int,
) -> list[tuple[Chunk, float]]:
    if not target_sources or max_results <= 0:
        return []

    preferred_sources = sorted(
        target_sources,
        key=lambda source_type: (-weights.get(source_type, 0.0), source_type),
    )
    selected: list[tuple[Chunk, float]] = []
    selected_ids: set[str] = set()

    for source_type in preferred_sources:
        candidate = next(
            (
                item
                for item in pool
                if item[0].source_type == source_type and item[0].chunk_id not in selected_ids
            ),
            None,
        )
        if candidate is not None:
            selected.append(candidate)
            selected_ids.add(candidate[0].chunk_id)
            if len(selected) >= max_results:
                return selected

    for item in pool:
        chunk = item[0]
        if chunk.source_type not in target_sources or chunk.chunk_id in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(chunk.chunk_id)
        if len(selected) >= max_results:
            break

    return selected


def format_source_types(source_types: set[str], weights: dict[str, float]) -> str:
    ordered = sorted(source_types, key=lambda source_type: (-weights.get(source_type, 0.0), source_type))
    return "、".join(SOURCE_TYPE_TRACE_LABELS.get(source_type, source_type) for source_type in ordered)
