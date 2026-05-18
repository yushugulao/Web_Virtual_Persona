from __future__ import annotations

from app.backend.core.config import get_settings
from app.backend.schemas.chat import ChatResponse
from app.backend.schemas.common import Citation, VerificationResult
from app.backend.schemas.retrieval import RetrievalTrace, RetrieveResponse
from app.backend.services.metadata_store import MetadataStore


PUBLIC_PERSONA_SOURCE_LABEL = "公开分身资料"
PUBLIC_PERSONA_SOURCE_PREVIEW = "该分身资料详情仅创建者可见。"


def metadata_store() -> MetadataStore:
    return MetadataStore(get_settings().sqlite_path)


def public_user_persona_is_readonly_for_user(
    *,
    persona_id: str,
    user_id: str,
    store: MetadataStore | None = None,
) -> bool:
    if not persona_id.startswith("user_persona_"):
        return False
    row = (store or metadata_store()).get_user_persona(persona_id)
    if row is None:
        return False
    return bool(row["is_public"]) and row["runtime_status"] == "ready" and row["owner_user_id"] != user_id


def sanitize_retrieve_response_for_public_persona(response: RetrieveResponse) -> RetrieveResponse:
    citations = _sanitize_citations(response.citations)
    trace = _sanitize_trace(response.trace, citations)
    return response.model_copy(update={"citations": citations, "trace": trace})


def sanitize_chat_response_for_public_persona(response: ChatResponse) -> ChatResponse:
    citations = _sanitize_citations(response.citations)
    trace = _sanitize_trace(response.retrieval_trace, citations)
    verification = _sanitize_verification(response.verification)
    return response.model_copy(
        update={
            "citations": citations,
            "retrieval_trace": trace,
            "verification": verification,
            "diagnostics": None,
        }
    )


def _sanitize_citations(citations: list[Citation]) -> list[Citation]:
    return [
        citation.model_copy(
            update={
                "chunk_id": f"public_persona_citation_{index:02d}",
                "doc_id": "public_persona_material",
                "title": PUBLIC_PERSONA_SOURCE_LABEL,
                "source_path": PUBLIC_PERSONA_SOURCE_LABEL,
                "section_path": "",
                "preview": PUBLIC_PERSONA_SOURCE_PREVIEW,
            }
        )
        for index, citation in enumerate(citations, 1)
    ]


def _sanitize_trace(trace: RetrievalTrace, citations: list[Citation]) -> RetrievalTrace:
    notes = [
        note
        for note in trace.notes
        if "path" not in note.lower()
        and "source_path" not in note.lower()
        and "corpus/" not in note
        and "data/" not in note
    ]
    notes.append("公开分身资料详情仅创建者可见；本次返回已隐藏本地路径和原文预览。")
    return trace.model_copy(
        update={
            "candidates": citations,
            "selected_chunk_ids": [citation.chunk_id for citation in citations],
            "notes": notes,
        }
    )


def _sanitize_verification(verification: VerificationResult) -> VerificationResult:
    claims = [
        claim.model_copy(update={"best_citation_ids": []})
        for claim in verification.claims
    ]
    return verification.model_copy(update={"claims": claims})
