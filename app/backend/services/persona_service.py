import json
from pathlib import Path

from app.backend.core.config import get_settings
from app.backend.schemas.personas import PersonaProfile


DEFAULT_PERSONA_ID = "local_persona"
PERSONA_CONFIG_PATH = Path("configs/personas.json")
_PERSONA_CACHE: tuple[tuple[int, int], list[PersonaProfile]] | None = None


def list_personas() -> list[PersonaProfile]:
    global _PERSONA_CACHE
    signature = _config_signature()
    if _PERSONA_CACHE and _PERSONA_CACHE[0] == signature:
        return _PERSONA_CACHE[1]
    raw = json.loads(PERSONA_CONFIG_PATH.read_text(encoding="utf-8"))
    personas = [PersonaProfile.model_validate(item) for item in raw]
    ensure_persona_registry_is_valid(personas)
    _PERSONA_CACHE = (signature, personas)
    return personas


def clear_persona_cache() -> None:
    global _PERSONA_CACHE
    _PERSONA_CACHE = None


def _config_signature() -> tuple[int, int]:
    stat = PERSONA_CONFIG_PATH.stat()
    return stat.st_mtime_ns, stat.st_size


def ensure_persona_registry_is_valid(personas: list[PersonaProfile]) -> None:
    ids = [persona.id for persona in personas]
    if DEFAULT_PERSONA_ID not in ids:
        raise ValueError(f"{PERSONA_CONFIG_PATH} must include {DEFAULT_PERSONA_ID}.")
    duplicates = sorted({persona_id for persona_id in ids if ids.count(persona_id) > 1})
    if duplicates:
        raise ValueError(f"Duplicate persona id(s) in {PERSONA_CONFIG_PATH}: {duplicates}")
    for persona in personas:
        if not persona.suggested_questions:
            raise ValueError(f"Persona {persona.id} must define at least one suggested question.")
        if not persona.boundary_note.strip():
            raise ValueError(f"Persona {persona.id} must define boundary_note.")
        if persona.id != DEFAULT_PERSONA_ID and not persona.retrieval_prefixes:
            raise ValueError(f"Persona {persona.id} must define retrieval_prefixes.")


def persona_map() -> dict[str, PersonaProfile]:
    return {persona.id: persona for persona in list_personas()}


def get_persona(persona_id: str | None) -> PersonaProfile:
    effective_id = normalize_persona_id(persona_id)
    system_persona = persona_map().get(effective_id)
    if system_persona:
        return system_persona
    custom_persona = _custom_persona_profile(effective_id)
    if custom_persona:
        return custom_persona
    return persona_map()[DEFAULT_PERSONA_ID]


def normalize_persona_id(persona_id: str | None) -> str:
    if not persona_id:
        return DEFAULT_PERSONA_ID
    candidate = persona_id.strip()
    if candidate in persona_map():
        return candidate
    if _custom_persona_profile(candidate):
        return candidate
    return DEFAULT_PERSONA_ID


def is_known_persona_id(persona_id: str | None) -> bool:
    if not persona_id:
        return True
    candidate = persona_id.strip()
    return candidate in persona_map() or _custom_persona_profile(candidate) is not None


def persona_retrieval_prefixes(persona_id: str | None) -> list[str]:
    persona = get_persona(persona_id)
    if persona.retrieval_prefixes:
        return [normalize_prefix(prefix) for prefix in persona.retrieval_prefixes]
    if persona.id == DEFAULT_PERSONA_ID:
        return ["corpus/"]
    return [f"corpus/personas/{persona.id}/"]


def named_persona_retrieval_prefixes() -> list[str]:
    prefixes: list[str] = []
    for persona in list_personas():
        if persona.id == DEFAULT_PERSONA_ID:
            continue
        prefixes.extend(persona_retrieval_prefixes(persona.id))
    return prefixes


def normalize_prefix(prefix: str) -> str:
    normalized = prefix.replace("\\", "/")
    return normalized if normalized.endswith("/") else f"{normalized}/"


def _custom_persona_profile(persona_id: str) -> PersonaProfile | None:
    if not persona_id.startswith("user_persona_"):
        return None
    try:
        from app.backend.services.metadata_store import MetadataStore

        row = MetadataStore(get_settings().sqlite_path).get_user_persona(persona_id)
    except Exception:  # noqa: BLE001 - persona normalization must fail closed.
        return None
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
