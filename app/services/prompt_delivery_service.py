from __future__ import annotations

import json

from ..db import get_conn
from .workspace_service import now_iso


def create_prompt_delivery(
    slug: str,
    agent_id: str,
    *,
    run_id: str | None,
    session_id: str | None,
    turn_no: int,
    last_read_before: int | None,
    last_delivered_before: int | None,
    delivered_upto: int | None,
    message_ids: list[int],
    status: str = "sent",
) -> dict:
    ts = now_iso()
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO prompt_deliveries (
                topic_slug, agent_id, run_id, session_id, turn_no, status,
                last_read_before, last_delivered_before, delivered_upto,
                message_ids_json, message_count, response_message_id,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                slug,
                agent_id,
                run_id,
                session_id,
                turn_no,
                status,
                last_read_before,
                last_delivered_before,
                delivered_upto,
                json.dumps(message_ids, ensure_ascii=False),
                len(message_ids),
                ts,
                ts,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM prompt_deliveries WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return dict(row)


def update_prompt_delivery(
    delivery_id: int,
    *,
    run_id: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
    delivered_upto: int | None = None,
    response_message_id: int | None = None,
) -> dict:
    ts = now_iso()
    with get_conn() as conn:
        current = conn.execute(
            "SELECT * FROM prompt_deliveries WHERE id = ?",
            (delivery_id,),
        ).fetchone()
        if current is None:
            raise KeyError(f"prompt_delivery {delivery_id} not found")

        next_run_id = current["run_id"] if run_id is None else run_id
        next_session_id = current["session_id"] if session_id is None else session_id
        next_status = current["status"] if status is None else status
        next_delivered_upto = current["delivered_upto"] if delivered_upto is None else delivered_upto
        next_response_message_id = (
            current["response_message_id"]
            if response_message_id is None
            else response_message_id
        )

        conn.execute(
            """
            UPDATE prompt_deliveries
            SET run_id = ?, session_id = ?, status = ?, delivered_upto = ?,
                response_message_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                next_run_id,
                next_session_id,
                next_status,
                next_delivered_upto,
                next_response_message_id,
                ts,
                delivery_id,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM prompt_deliveries WHERE id = ?",
            (delivery_id,),
        ).fetchone()
    return dict(row)


def list_prompt_deliveries(slug: str, limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM prompt_deliveries
            WHERE topic_slug = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (slug, limit),
        ).fetchall()
    return [dict(row) for row in rows]
