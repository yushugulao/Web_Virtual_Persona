import json
import logging
import time
from collections.abc import Mapping
from typing import Any
from uuid import uuid4


logger = logging.getLogger("persona_rag")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def new_request_id() -> str:
    return uuid4().hex[:16]


def log_event(event: str, payload: Mapping[str, Any] | None = None) -> None:
    record = {
        "ts": round(time.time(), 3),
        "event": event,
        **dict(payload or {}),
    }
    logger.info(json.dumps(record, ensure_ascii=False))

