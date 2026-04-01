from __future__ import annotations

from ..db import get_conn
from .workspace_service import now_iso


def append_message(
    slug: str,
    speaker_id: str,
    content: str,
    *,
    speaker_type: str | None = None,
    created_at: str | None = None,
) -> dict:
    normalized_speaker_type = speaker_type or ("user" if speaker_id == "user" else "agent")
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO messages (topic_slug, speaker_type, speaker_id, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (slug, normalized_speaker_type, speaker_id, content.strip(), created_at or now_iso()),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT id, topic_slug, speaker_type, speaker_id, content, created_at
            FROM messages
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
    return dict(row)


def list_messages(slug: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, topic_slug, speaker_type, speaker_id, content, created_at
            FROM messages
            WHERE topic_slug = ?
            ORDER BY id ASC
            """,
            (slug,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_messages_after(slug: str, message_id: int | None) -> list[dict]:
    if message_id is None:
        return list_messages(slug)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, topic_slug, speaker_type, speaker_id, content, created_at
            FROM messages
            WHERE topic_slug = ? AND id > ?
            ORDER BY id ASC
            """,
            (slug, message_id),
        ).fetchall()
    return [dict(row) for row in rows]


def list_messages_between(
    slug: str,
    after_message_id: int | None,
    upto_message_id: int | None,
) -> list[dict]:
    if upto_message_id is None:
        return []
    lower_bound = -1 if after_message_id is None else after_message_id
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, topic_slug, speaker_type, speaker_id, content, created_at
            FROM messages
            WHERE topic_slug = ? AND id > ? AND id <= ?
            ORDER BY id ASC
            """,
            (slug, lower_bound, upto_message_id),
        ).fetchall()
    return [dict(row) for row in rows]


def latest_message_id(slug: str) -> int | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(id) AS max_id FROM messages WHERE topic_slug = ?",
            (slug,),
        ).fetchone()
    return row["max_id"] if row and row["max_id"] is not None else None
