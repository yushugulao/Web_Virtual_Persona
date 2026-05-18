from __future__ import annotations

from typing import Any

from app.backend.core.config import get_settings
from app.backend.schemas.persona_catalog import PersonaCatalogCard, UserPersonaDetail
from app.backend.schemas.personas import PersonaProfile
from app.backend.services.metadata_store import MetadataStore
from app.backend.services.persona_service import list_personas, persona_map


def metadata_store() -> MetadataStore:
    return MetadataStore(get_settings().sqlite_path)


def system_persona_cards() -> list[PersonaCatalogCard]:
    store = metadata_store()
    return [_system_card(persona, store.persona_score(persona.id)) for persona in list_personas()]


def search_persona_catalog(*, query: str, user_id: str, limit: int = 24) -> list[PersonaCatalogCard]:
    clean_query = " ".join(query.split()).lower()
    system_cards = [
        card
        for card in system_persona_cards()
        if not clean_query or _card_matches(card, clean_query)
    ]
    user_cards = [
        _user_card(row, current_user_id=user_id)
        for row in metadata_store().search_public_user_personas(
            query=clean_query,
            current_user_id=None,
            limit=limit,
        )
    ]
    combined = [*system_cards, *user_cards]
    return combined[:limit]


def list_public_user_personas(
    *,
    query: str,
    user_id: str,
    limit: int = 24,
    offset: int = 0,
    sort: str = "published_at",
) -> tuple[int, list[PersonaCatalogCard]]:
    store = metadata_store()
    total = store.count_public_user_personas(query=query)
    rows = store.list_public_user_personas(
        query=query,
        limit=limit,
        offset=offset,
        sort=sort,
    )
    return total, [_user_card(row, current_user_id=user_id) for row in rows]


def recommended_public_user_personas(*, user_id: str, limit: int = 5) -> tuple[int, list[PersonaCatalogCard]]:
    rows = metadata_store().top_public_user_personas(current_user_id=None, limit=limit)
    return len(rows), [_user_card(row, current_user_id=user_id) for row in rows]


def list_my_user_personas(*, user_id: str) -> list[UserPersonaDetail]:
    return [_user_detail(row, current_user_id=user_id) for row in metadata_store().list_user_personas(owner_user_id=user_id)]


def create_draft_user_persona(
    *,
    user_id: str,
    name: str,
    description: str,
    web_search_enabled: bool,
) -> UserPersonaDetail:
    from app.backend.services.user_persona_upload_service import create_draft_persona

    row = create_draft_persona(
        user_id=user_id,
        name=name,
        description=description,
        web_search_enabled=web_search_enabled,
    )
    return _user_detail(row, current_user_id=user_id)


def get_user_persona_detail(*, persona_id: str, user_id: str) -> UserPersonaDetail | None:
    row = metadata_store().get_user_persona(persona_id)
    if row is None:
        return None
    is_owner = row["owner_user_id"] == user_id
    if not is_owner and (not row["is_public"] or row["runtime_status"] != "ready"):
        return None
    return _user_detail(row, current_user_id=user_id, redact_private=not is_owner)


def publish_user_persona(*, persona_id: str, user_id: str) -> UserPersonaDetail | None:
    row = metadata_store().publish_user_persona(owner_user_id=user_id, persona_id=persona_id)
    return _user_detail(row, current_user_id=user_id) if row else None


def unpublish_user_persona(*, persona_id: str, user_id: str) -> UserPersonaDetail | None:
    row = metadata_store().unpublish_user_persona(owner_user_id=user_id, persona_id=persona_id)
    return _user_detail(row, current_user_id=user_id) if row else None


def resolve_chat_persona_id(*, persona_id: str | None, user_id: str) -> str | None:
    if not persona_id:
        return None
    candidate = persona_id.strip()
    if candidate in persona_map():
        return candidate
    row = metadata_store().get_user_persona(candidate)
    if row is None:
        return None
    if row["runtime_status"] != "ready":
        return None
    if row["owner_user_id"] == user_id or row["is_public"]:
        return candidate
    return None


def persona_display_name(persona_id: str) -> str:
    system = persona_map().get(persona_id)
    if system:
        return system.name
    row = metadata_store().get_user_persona(persona_id)
    return str(row["name"]) if row else persona_id


def custom_persona_profile(persona_id: str) -> PersonaProfile | None:
    row = metadata_store().get_user_persona(persona_id)
    if row is None or row["runtime_status"] != "ready":
        return None
    return PersonaProfile(
        id=row["persona_id"],
        name=row["name"],
        subtitle=row["short_description"] or "用户创建的虚拟分身",
        description=row["description"] or row["short_description"] or "用户创建的虚拟分身。",
        avatar_label=row["avatar_label"] or "分",
        avatar_url=row["avatar_url"],
        identity_tags=row["identity_tags"],
        source_note="用户创建的虚拟分身资料。",
        boundary_note="这个分身来自用户创建资料；没有资料支撑的细节应当保持谨慎。",
        corpus_paths=[f"corpus/user_personas/{row['persona_id']}/*.md"],
        retrieval_prefixes=[f"corpus/user_personas/{row['persona_id']}/"],
        raw_source_paths=[],
        source_urls=[],
        suggested_questions=["你最近想聊什么？"],
    )


def _system_card(persona: PersonaProfile, score: int) -> PersonaCatalogCard:
    tags = persona.identity_tags or _tags_from_subtitle(persona.subtitle)
    return PersonaCatalogCard(
        id=persona.id,
        name=persona.name,
        avatar_url=persona.avatar_url,
        avatar_label=persona.avatar_label,
        identity_tags=tags[:4],
        short_description=_short_description(persona),
        kind="system",
        runtime_status="ready",
        score=score,
        is_owner=False,
    )


def _user_card(row: dict[str, Any], *, current_user_id: str) -> PersonaCatalogCard:
    return PersonaCatalogCard(
        id=row["persona_id"],
        name=row["name"],
        avatar_url=row["avatar_url"],
        avatar_label=row["avatar_label"],
        identity_tags=list(row["identity_tags"])[:4],
        short_description=row["short_description"],
        kind="user",
        runtime_status=row["runtime_status"],
        score=int(row["score"]),
        is_owner=row["owner_user_id"] == current_user_id,
        is_public=bool(row["is_public"]),
        published_at=row["published_at"],
    )


def _user_detail(row: dict[str, Any], *, current_user_id: str, redact_private: bool = False) -> UserPersonaDetail:
    card = _user_card(row, current_user_id=current_user_id)
    return UserPersonaDetail(
        **card.model_dump(),
        owner_user_id="" if redact_private else row["owner_user_id"],
        description=row["description"],
        web_search_enabled=bool(row.get("web_search_enabled", False)),
        source_depth="" if redact_private else row.get("source_depth", ""),
        evidence_card_count=0 if redact_private else int(row.get("evidence_card_count", 0) or 0),
        build_error="" if redact_private else row.get("build_error", ""),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )


def _card_matches(card: PersonaCatalogCard, query: str) -> bool:
    haystack = " ".join([card.id, card.name, card.short_description, *card.identity_tags]).lower()
    return query in haystack


def _tags_from_subtitle(subtitle: str) -> list[str]:
    separators = ["，", "、", "/", "·", "|", ","]
    current = subtitle
    for separator in separators:
        current = current.replace(separator, " ")
    tags = [part.strip() for part in current.split() if part.strip()]
    return tags[:4] or ["虚拟分身"]


def _short_description(persona: PersonaProfile) -> str:
    if persona.identity_tags:
        return " / ".join(persona.identity_tags[:3])
    return persona.subtitle or persona.description[:32]
