from __future__ import annotations

import json
import logging

logger = logging.getLogger("agent_deliberation.events")


def append_event(slug: str, payload: dict) -> None:
    logger.info("topic=%s event=%s", slug, json.dumps(payload, ensure_ascii=False))


def read_events(slug: str, limit: int = 300) -> list[dict]:
    return []
