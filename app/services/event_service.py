from __future__ import annotations

import json
import logging

from .workspace_service import append_text, workspace_files

logger = logging.getLogger("agent_deliberation.events")


def append_event(slug: str, payload: dict) -> None:
    event_path = workspace_files(slug)["events"]
    append_text(event_path, json.dumps(payload, ensure_ascii=False) + "\n")
    logger.info("topic=%s event=%s", slug, json.dumps(payload, ensure_ascii=False))


def read_events(slug: str, limit: int = 300) -> list[dict]:
    event_path = workspace_files(slug)["events"]
    if not event_path.exists():
        return []

    lines = event_path.read_text(encoding="utf-8").splitlines()
    events: list[dict] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events
