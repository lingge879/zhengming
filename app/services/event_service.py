from __future__ import annotations

import json
import logging

logger = logging.getLogger("agent_deliberation.events")


_NOISY_DELTA_TYPES = {"text_delta", "thinking_delta"}


def _is_stream_delta(payload: dict) -> bool:
    event = payload.get("event", {})
    if not isinstance(event, dict):
        return False
    nested = event.get("event", {})
    if not isinstance(nested, dict):
        return False
    delta = nested.get("delta", {})
    return isinstance(delta, dict) and delta.get("type") in _NOISY_DELTA_TYPES


def append_event(slug: str, payload: dict) -> None:
    if _is_stream_delta(payload):
        return  # skip per-token deltas from log
    logger.info("topic=%s event=%s", slug, json.dumps(payload, ensure_ascii=False))


def read_events(slug: str, limit: int = 300) -> list[dict]:
    return []
