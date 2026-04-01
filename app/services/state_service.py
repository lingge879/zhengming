from __future__ import annotations

import json

from ..config import DEFAULT_SPEAKER_ORDER
from ..db import get_conn
from .workspace_service import now_iso


def load_state(slug: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT slug, title, status, turn_no, speaker_order, current_speaker,
                   last_message_id, created_at, updated_at
            FROM topics
            WHERE slug = ?
            """,
            (slug,),
        ).fetchone()
    if row is None:
        raise FileNotFoundError(slug)
    return {
        "topic_slug": row["slug"],
        "title": row["title"],
        "status": row["status"],
        "turn_no": row["turn_no"],
        "speaker_order": json.loads(row["speaker_order"] or "[]") or DEFAULT_SPEAKER_ORDER,
        "current_speaker": row["current_speaker"],
        "last_message_id": row["last_message_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def save_state(slug: str, state: dict) -> None:
    state["updated_at"] = now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE topics
            SET title = ?, status = ?, turn_no = ?, speaker_order = ?, current_speaker = ?,
                last_message_id = ?, created_at = ?, updated_at = ?
            WHERE slug = ?
            """,
            (
                state["title"],
                state["status"],
                state["turn_no"],
                json.dumps(state["speaker_order"], ensure_ascii=False),
                state["current_speaker"],
                state.get("last_message_id"),
                state["created_at"],
                state["updated_at"],
                slug,
            ),
        )
        conn.commit()


def set_speaker_order(slug: str, agent_order: list[str]) -> dict:
    state = load_state(slug)
    state["speaker_order"] = ["user", *agent_order]
    if state["current_speaker"] not in state["speaker_order"]:
        state["current_speaker"] = "user"
    save_state(slug, state)
    return state


def advance_speaker(slug: str) -> dict:
    state = load_state(slug)
    order = state["speaker_order"]
    current = state["current_speaker"]
    idx = order.index(current)
    if idx == len(order) - 1:
        state["turn_no"] += 1
        state["current_speaker"] = order[0]
    else:
        state["current_speaker"] = order[idx + 1]
    save_state(slug, state)
    return state
