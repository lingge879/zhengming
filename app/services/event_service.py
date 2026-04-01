from __future__ import annotations

import json

from .workspace_service import append_text, read_text, workspace_files


def append_event(slug: str, payload: dict) -> None:
    line = json.dumps(payload, ensure_ascii=False)
    append_text(workspace_files(slug)["events"], line + "\n")


def read_events(slug: str, limit: int = 300) -> list[dict]:
    raw = read_text(workspace_files(slug)["events"])
    lines = [line for line in raw.splitlines() if line.strip()]
    if limit > 0:
        lines = lines[-limit:]
    items = []
    for line in lines:
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            items.append({"parse_error": True, "raw": line})
    return items

