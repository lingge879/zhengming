from __future__ import annotations

from ..config import DEFAULT_AGENT_LIST
from ..db import get_conn
from .workspace_service import now_iso


def ensure_agent_states(slug: str) -> None:
    ts = now_iso()
    with get_conn() as conn:
        for agent_id in DEFAULT_AGENT_LIST:
            conn.execute(
                """
                INSERT INTO agent_states (
                    topic_slug, agent_id, session_id, last_read_message_id,
                    last_delivered_message_id, status, updated_at
                )
                VALUES (?, ?, NULL, NULL, NULL, 'idle', ?)
                ON CONFLICT(topic_slug, agent_id) DO NOTHING
                """,
                (slug, agent_id, ts),
            )
        conn.commit()


def load_agent_states(slug: str) -> dict[str, dict]:
    ensure_agent_states(slug)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT topic_slug, agent_id, session_id, last_read_message_id,
                   last_delivered_message_id, status, updated_at
            FROM agent_states
            WHERE topic_slug = ?
            ORDER BY agent_id ASC
            """,
            (slug,),
        ).fetchall()
    return {
        row["agent_id"]: {
            "topic_slug": row["topic_slug"],
            "agent_id": row["agent_id"],
            "session_id": row["session_id"],
            "last_read_message_id": row["last_read_message_id"],
            "last_delivered_message_id": row["last_delivered_message_id"],
            "status": row["status"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    }


def update_agent_state(
    slug: str,
    agent_id: str,
    *,
    session_id: str | None = None,
    last_read_message_id: int | None = None,
    last_delivered_message_id: int | None = None,
    status: str | None = None,
) -> dict:
    ensure_agent_states(slug)
    current = load_agent_states(slug).get(agent_id, {})
    next_session_id = current.get("session_id") if session_id is None else session_id
    next_last_read = current.get("last_read_message_id") if last_read_message_id is None else last_read_message_id
    next_last_delivered = (
        current.get("last_delivered_message_id")
        if last_delivered_message_id is None
        else last_delivered_message_id
    )
    next_status = current.get("status", "idle") if status is None else status
    ts = now_iso()

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO agent_states (
                topic_slug, agent_id, session_id, last_read_message_id,
                last_delivered_message_id, status, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic_slug, agent_id) DO UPDATE SET
                session_id = excluded.session_id,
                last_read_message_id = excluded.last_read_message_id,
                last_delivered_message_id = excluded.last_delivered_message_id,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                slug,
                agent_id,
                next_session_id,
                next_last_read,
                next_last_delivered,
                next_status,
                ts,
            ),
        )
        conn.commit()
    return load_agent_states(slug)[agent_id]

