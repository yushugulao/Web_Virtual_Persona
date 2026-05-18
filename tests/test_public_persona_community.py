import pytest
from fastapi import HTTPException

from app.backend.api import persona_catalog as persona_catalog_api
from app.backend.schemas.auth import AuthUser
from app.backend.schemas.common import Citation, TimingBreakdown, VerificationClaim, VerificationResult
from app.backend.schemas.chat import ChatDiagnostics, ChatResponse
from app.backend.schemas.persona_catalog import PersonaCatalogCard, UserPersonaDetail
from app.backend.schemas.retrieval import RetrievalTrace, RetrieveResponse
from app.backend.services import persona_catalog_service
from app.backend.services.metadata_store import MetadataStore
from app.backend.services.persona_material_service import get_persona_materials
from app.backend.services.public_persona_policy import (
    PUBLIC_PERSONA_SOURCE_LABEL,
    PUBLIC_PERSONA_SOURCE_PREVIEW,
    public_user_persona_is_readonly_for_user,
    sanitize_chat_response_for_public_persona,
    sanitize_retrieve_response_for_public_persona,
)


def auth_user(user_id: str) -> AuthUser:
    return AuthUser(
        id=user_id,
        email=f"{user_id}@example.test",
        username=user_id,
        role="user",
        status="active",
        email_verified=True,
        must_change_password=False,
        created_at="2026-01-01T00:00:00+08:00",
        updated_at="2026-01-01T00:00:00+08:00",
    )


def test_ready_persona_can_publish_but_draft_cannot(tmp_path):
    store = MetadataStore(tmp_path / "persona.sqlite3")
    ready = store.create_user_persona(owner_user_id="owner", name="Ready", runtime_status="ready")
    draft = store.create_user_persona(owner_user_id="owner", name="Draft", runtime_status="draft")

    published = store.publish_user_persona(owner_user_id="owner", persona_id=ready["persona_id"])
    unchanged = store.publish_user_persona(owner_user_id="owner", persona_id=draft["persona_id"])

    assert published is not None
    assert published["is_public"] is True
    assert published["published_at"] is not None
    assert unchanged is not None
    assert unchanged["is_public"] is False
    assert unchanged["runtime_status"] == "draft"


def test_publish_endpoint_returns_clear_error_for_non_ready_persona(monkeypatch):
    def fake_publish_user_persona(*, persona_id: str, user_id: str) -> UserPersonaDetail:
        return UserPersonaDetail(
            id=persona_id,
            name="Draft",
            avatar_label="D",
            identity_tags=[],
            short_description="draft",
            kind="user",
            runtime_status="draft",
            score=0,
            is_owner=True,
            is_public=False,
            owner_user_id=user_id,
            description="draft",
            created_at=1.0,
            updated_at=1.0,
        )

    monkeypatch.setattr(persona_catalog_api, "publish_user_persona", fake_publish_user_persona)

    with pytest.raises(HTTPException) as exc_info:
        persona_catalog_api.publish_user_persona_endpoint("user_persona_draft", user=auth_user("owner"))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "请先生成完成后再公开。"


def test_public_catalog_only_lists_ready_public_personas(tmp_path):
    store = MetadataStore(tmp_path / "persona.sqlite3")
    public_ready = store.create_user_persona(
        owner_user_id="owner",
        name="Public Ready",
        short_description="searchable profile",
        identity_tags=["alpha"],
        runtime_status="ready",
        is_public=True,
    )
    store.create_user_persona(owner_user_id="owner", name="Private Ready", runtime_status="ready")
    store.create_user_persona(owner_user_id="owner", name="Public Draft", runtime_status="draft", is_public=True)

    rows = store.list_public_user_personas(query="searchable", limit=10, offset=0, sort="published_at")

    assert store.count_public_user_personas(query="searchable") == 1
    assert [row["persona_id"] for row in rows] == [public_ready["persona_id"]]

    store.unpublish_user_persona(owner_user_id="owner", persona_id=public_ready["persona_id"])
    assert store.count_public_user_personas() == 0


def test_public_catalog_endpoint_returns_pagination_shape(monkeypatch):
    expected_card = PersonaCatalogCard(
        id="user_persona_public",
        name="Public Persona",
        avatar_label="P",
        identity_tags=["tag"],
        short_description="ready public persona",
        kind="user",
        runtime_status="ready",
        score=7,
        is_owner=False,
        is_public=True,
        published_at=1.0,
    )

    def fake_list_public_user_personas(
        *,
        query: str,
        user_id: str,
        limit: int,
        offset: int,
        sort: str,
    ) -> tuple[int, list[PersonaCatalogCard]]:
        assert query == "public"
        assert user_id == "viewer"
        assert limit == 24
        assert offset == 0
        assert sort == "published_at"
        return 1, [expected_card]

    monkeypatch.setattr(persona_catalog_api, "list_public_user_personas", fake_list_public_user_personas)

    response = persona_catalog_api.public_user_persona_catalog(
        q="public",
        limit=24,
        offset=0,
        sort="published_at",
        user=auth_user("viewer"),
    )

    assert response.total == 1
    assert response.results == [expected_card]
    assert response.sort == "published_at"


def test_public_persona_detail_redacts_non_owner_fields(tmp_path, monkeypatch):
    store = MetadataStore(tmp_path / "persona.sqlite3")
    persona = store.create_user_persona(
        owner_user_id="owner",
        name="Shared",
        runtime_status="ready",
        is_public=True,
    )
    monkeypatch.setattr(persona_catalog_service, "metadata_store", lambda: store)

    detail = persona_catalog_service.get_user_persona_detail(
        persona_id=persona["persona_id"],
        user_id="viewer",
    )

    assert detail is not None
    assert detail.is_owner is False
    assert detail.owner_user_id == ""
    assert detail.evidence_card_count == 0
    assert detail.build_error == ""


def test_non_owner_materials_are_hidden_for_public_personas(tmp_path):
    store = MetadataStore(tmp_path / "persona.sqlite3")
    public_persona = store.create_user_persona(
        owner_user_id="owner",
        name="Shared",
        runtime_status="ready",
        is_public=True,
    )
    private_persona = store.create_user_persona(
        owner_user_id="owner",
        name="Private",
        runtime_status="ready",
        is_public=False,
    )

    response = get_persona_materials(
        public_persona["persona_id"],
        project_root=tmp_path,
        user_id="viewer",
        store=store,
    )

    assert response.documents == []
    assert response.corpus_paths == []
    assert response.raw_source_paths == []
    with pytest.raises(FileNotFoundError):
        get_persona_materials(
            private_persona["persona_id"],
            project_root=tmp_path,
            user_id="viewer",
            store=store,
        )


def test_public_chat_and_retrieval_policy_redacts_sources(tmp_path):
    store = MetadataStore(tmp_path / "persona.sqlite3")
    persona = store.create_user_persona(
        owner_user_id="owner",
        name="Shared",
        runtime_status="ready",
        is_public=True,
    )
    citation = Citation(
        chunk_id="secret-chunk",
        doc_id="secret-doc",
        title="source_expansion_private.md",
        source_path="C:/data/corpus/user_personas/shared/private.md",
        section_path="private/file",
        preview="raw private preview",
        score=0.9,
        trust_level="inferred",
        privacy_level="private",
    )
    response = RetrieveResponse(
        retrieval_id="retrieval-1",
        query="question",
        citations=[citation],
        trace=RetrievalTrace(
            original_query="question",
            persona_id=persona["persona_id"],
            candidates=[citation],
            selected_chunk_ids=["secret-chunk"],
            notes=["loaded from corpus/user_personas/shared/private.md", "kept note"],
        ),
        timings=TimingBreakdown(),
    )

    sanitized = sanitize_retrieve_response_for_public_persona(response)
    sanitized_citation = sanitized.citations[0]

    assert public_user_persona_is_readonly_for_user(
        persona_id=persona["persona_id"],
        user_id="viewer",
        store=store,
    )
    assert not public_user_persona_is_readonly_for_user(
        persona_id=persona["persona_id"],
        user_id="owner",
        store=store,
    )
    assert sanitized_citation.title == PUBLIC_PERSONA_SOURCE_LABEL
    assert sanitized_citation.source_path == PUBLIC_PERSONA_SOURCE_LABEL
    assert sanitized_citation.preview == PUBLIC_PERSONA_SOURCE_PREVIEW
    assert sanitized.trace.selected_chunk_ids == [sanitized_citation.chunk_id]
    assert all("corpus/" not in note for note in sanitized.trace.notes)


def test_verification_claims_can_be_redacted_without_losing_structure():
    citation = Citation(
        chunk_id="secret-chunk",
        doc_id="secret-doc",
        title="private",
        source_path="C:/private.md",
        section_path="section",
        preview="raw",
        score=0.8,
        trust_level="inferred",
        privacy_level="private",
    )
    response = ChatResponse(
        answer="answer",
        mode="rag",
        confidence="medium",
        follow_up_questions=[],
        citations=[citation],
        retrieval_trace=RetrievalTrace(original_query="question", candidates=[citation]),
        verification=VerificationResult(
            claim_count=1,
            supported_claim_count=1,
            claim_support_rate=1,
            claims=[VerificationClaim(text="claim", supported=True, best_citation_ids=["secret-chunk"])],
        ),
        timings=TimingBreakdown(),
        model="test",
        request_id="request-1",
        session_id="session-1",
        diagnostics=ChatDiagnostics(enabled=True),
    )

    sanitized = sanitize_chat_response_for_public_persona(response)

    assert sanitized.citations[0].chunk_id != "secret-chunk"
    assert sanitized.verification.claims[0].best_citation_ids == []
    assert sanitized.diagnostics is None
