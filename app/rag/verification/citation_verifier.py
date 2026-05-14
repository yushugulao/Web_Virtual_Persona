from __future__ import annotations

import re

from app.backend.schemas.common import Citation, VerificationClaim, VerificationResult
from app.rag.retrieval.lexical import tokenize


CLAIM_SPLIT_RE = re.compile(r"(?<=[。！？!?；;.])\s*|\n+")
CJK_SEGMENT_RE = re.compile(r"[\u4e00-\u9fff]+")
NON_CLAIM_PUNCT_RE = re.compile(r"[\s,，。.!！?？:：;；~～]+")

STOPWORDS = {
    "about",
    "also",
    "and",
    "are",
    "based",
    "but",
    "can",
    "cannot",
    "does",
    "from",
    "have",
    "into",
    "not",
    "that",
    "the",
    "this",
    "using",
    "what",
    "which",
    "with",
    "一个",
    "不是",
    "以及",
    "可以",
    "如果",
    "没有",
    "这个",
    "这些",
    "进行",
}

LOW_EVIDENCE_MARKERS = (
    "not enough evidence",
    "no evidence",
    "cannot answer",
    "无法",
    "不能",
    "没有足够",
    "当前材料不足",
    "公开材料不提供",
    "未提及",
    "未被提及",
    "没有提到",
    "无法确认",
    "不能把",
    "不会公开",
    "不会编造",
    "不会说出",
    "不在我的经历",
    "不在我能够确认的经历",
    "不属于我的经历",
)

NON_CLAIM_UTTERANCES = {
    "hi",
    "hello",
    "hey",
    "ok",
    "okay",
    "sure",
    "thanks",
    "thankyou",
    "您好",
    "你好",
    "谢谢",
    "感谢",
    "好的",
    "可以",
    "当然",
    "根据材料",
    "基于材料",
    "根据证据",
}


def verify_answer(
    answer: str | None,
    citations: list[Citation],
    *,
    min_support_score: float = 0.12,
) -> VerificationResult:
    if not answer:
        return VerificationResult()
    claims = [
        verify_claim(claim, citations, min_support_score=min_support_score)
        for claim in split_claims(answer)
    ]
    supported_count = sum(1 for claim in claims if claim.supported)
    unsupported = [claim.text for claim in claims if not claim.supported]
    total = len(claims)
    return VerificationResult(
        claim_count=total,
        supported_claim_count=supported_count,
        unsupported_claim_count=len(unsupported),
        claim_support_rate=round(supported_count / total, 4) if total else 0.0,
        unsupported_claims=unsupported,
        claims=claims,
    )


def verify_claim(
    claim: str,
    citations: list[Citation],
    *,
    min_support_score: float,
) -> VerificationClaim:
    claim_terms = content_terms(claim)
    if not claim_terms:
        return VerificationClaim(text=claim, support_score=1.0, supported=True)
    if contains_low_evidence_marker(claim):
        return VerificationClaim(text=claim, support_score=1.0, supported=True)

    best_score = 0.0
    best_citations: list[str] = []
    aggregate_terms: set[str] = set()
    citation_overlaps: list[tuple[str, int]] = []
    for citation in citations:
        evidence_terms = citation_terms(citation)
        if not evidence_terms:
            continue
        aggregate_terms.update(evidence_terms)
        overlap_count = len(claim_terms & evidence_terms)
        if overlap_count:
            citation_overlaps.append((citation.chunk_id, overlap_count))
        score = len(claim_terms & evidence_terms) / len(claim_terms)
        if score > best_score:
            best_score = score
            best_citations = [citation.chunk_id]
        elif score == best_score and score > 0:
            best_citations.append(citation.chunk_id)

    aggregate_score = (
        len(claim_terms & aggregate_terms) / len(claim_terms)
        if aggregate_terms
        else 0.0
    )
    support_score = max(best_score, aggregate_score)
    if aggregate_score > best_score and citation_overlaps:
        best_citations = [
            chunk_id
            for chunk_id, _overlap in sorted(
                citation_overlaps,
                key=lambda item: item[1],
                reverse=True,
            )
        ]

    return VerificationClaim(
        text=claim,
        support_score=round(support_score, 4),
        supported=support_score >= min_support_score,
        best_citation_ids=best_citations[:3],
    )


def split_claims(answer: str) -> list[str]:
    return [
        clean
        for part in CLAIM_SPLIT_RE.split(answer)
        if (clean := part.strip()) and not is_non_claim_utterance(clean)
    ]


def citation_terms(citation: Citation) -> set[str]:
    return content_terms(" ".join([citation.title, citation.section_path, citation.preview]))


def content_terms(text: str) -> set[str]:
    terms = {
        token
        for token in tokenize(text)
        if len(token) >= 2 and token not in STOPWORDS and not token.isdigit()
    }
    for segment in CJK_SEGMENT_RE.findall(text):
        terms.update(
            segment[index : index + 2]
            for index in range(max(0, len(segment) - 1))
        )
    return terms


def contains_low_evidence_marker(text: str) -> bool:
    normalized = text.lower()
    return any(marker.lower() in normalized for marker in LOW_EVIDENCE_MARKERS)


def is_non_claim_utterance(text: str) -> bool:
    normalized = NON_CLAIM_PUNCT_RE.sub("", text).lower()
    return normalized in NON_CLAIM_UTTERANCES
