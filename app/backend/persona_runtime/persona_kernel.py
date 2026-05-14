from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

from app.backend.core.config import get_settings


HISTORICAL_PERSONA_IDS = (
    "benjamin_franklin",
    "nikola_tesla",
    "helen_keller",
    "charles_darwin",
)

REQUIRED_KERNEL_FIELDS = (
    "display_name",
    "rhythm",
    "emotional_posture",
    "boundary_posture",
    "conversation_principles",
    "overused_themes",
    "factual_anchors",
    "scenes",
)


@dataclass(frozen=True)
class PersonaKernel:
    persona_id: str
    display_name: str
    rhythm: str
    emotional_posture: str
    boundary_posture: str
    conversation_principles: tuple[str, ...]
    overused_themes: tuple[str, ...]
    factual_anchors: tuple[str, ...]
    scenes: dict[str, tuple[str, ...]]


def get_persona_kernel(persona_id: str) -> PersonaKernel:
    kernels = load_persona_kernels()
    if persona_id in kernels:
        return kernels[persona_id]
    custom = _load_custom_persona_kernel(persona_id)
    if custom is not None:
        return custom
    raise KeyError(f"Missing persona kernel for {persona_id}")


def format_kernel_for_actor(kernel: PersonaKernel, speech_act: str) -> str:
    scene_lines = kernel.scenes.get(speech_act) or kernel.scenes.get("chitchat") or ()
    principles = "\n".join(f"- {item}" for item in kernel.conversation_principles)
    scene_text = "\n".join(f"- {item}" for item in scene_lines)
    avoid_text = "、".join(kernel.overused_themes)
    factual_text = ""
    if speech_act == "factual" and kernel.factual_anchors:
        anchor_lines = "\n".join(f"- {item}" for item in kernel.factual_anchors)
        factual_text = f"本轮可用的高置信事实锚点：\n{anchor_lines}\n"
    return (
        f"人物：{kernel.display_name}\n"
        f"说话节奏：{kernel.rhythm}\n"
        f"情绪姿态：{kernel.emotional_posture}\n"
        f"边界姿态：{kernel.boundary_posture}\n"
        f"对话原则：\n{principles}\n"
        f"本轮场景姿态：\n{scene_text or '- 像真人一样先接住用户这句话。'}\n"
        f"{factual_text}"
        f"容易说腻的主题：{avoid_text}\n"
    )


def validate_persona_kernels(kernels: dict[str, PersonaKernel]) -> None:
    missing = [persona_id for persona_id in HISTORICAL_PERSONA_IDS if persona_id not in kernels]
    if missing:
        raise ValueError(f"Missing persona kernels: {', '.join(missing)}")
    for persona_id, kernel in kernels.items():
        if not kernel.conversation_principles:
            raise ValueError(f"Persona kernel {persona_id} has no conversation principles")
        if "chitchat" not in kernel.scenes:
            raise ValueError(f"Persona kernel {persona_id} has no chitchat scene")


@lru_cache(maxsize=1)
def load_persona_kernels(path: str | Path = "configs/persona_kernels.json") -> dict[str, PersonaKernel]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    kernels = {
        persona_id: parse_kernel(persona_id, raw)
        for persona_id, raw in payload.items()
    }
    validate_persona_kernels(kernels)
    return kernels


def parse_kernel(persona_id: str, raw: object) -> PersonaKernel:
    if not isinstance(raw, dict):
        raise ValueError(f"Persona kernel {persona_id} must be an object")
    missing = [field for field in REQUIRED_KERNEL_FIELDS if field not in raw]
    if missing:
        raise ValueError(f"Persona kernel {persona_id} missing fields: {', '.join(missing)}")
    scenes = raw["scenes"]
    if not isinstance(scenes, dict):
        raise ValueError(f"Persona kernel {persona_id} scenes must be an object")
    return PersonaKernel(
        persona_id=persona_id,
        display_name=str(raw["display_name"]),
        rhythm=str(raw["rhythm"]),
        emotional_posture=str(raw["emotional_posture"]),
        boundary_posture=str(raw["boundary_posture"]),
        conversation_principles=tuple(str(item) for item in raw["conversation_principles"]),
        overused_themes=tuple(str(item) for item in raw["overused_themes"]),
        factual_anchors=tuple(str(item) for item in raw["factual_anchors"]),
        scenes={
            str(scene): tuple(str(item) for item in values)
            for scene, values in scenes.items()
            if isinstance(values, list)
        },
    )


def _load_custom_persona_kernel(persona_id: str) -> PersonaKernel | None:
    path = get_settings().corpus_dir / "user_personas" / persona_id / "persona_kernel.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return parse_kernel(persona_id, raw)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
