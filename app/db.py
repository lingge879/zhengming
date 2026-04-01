from __future__ import annotations

import sqlite3
from contextlib import contextmanager
import json

from .config import DB_PATH, DATA_DIR


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS topics (
                slug TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                turn_no INTEGER NOT NULL DEFAULT 1,
                speaker_order TEXT NOT NULL DEFAULT '[]',
                current_speaker TEXT NOT NULL,
                last_message_id INTEGER,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                workspace_path TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "topics", "description", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "topics", "turn_no", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "topics", "speaker_order", f"TEXT NOT NULL DEFAULT '{json.dumps(['user', 'codex', 'claudecode'])}'")
        _ensure_column(conn, "topics", "last_message_id", "INTEGER")
        _ensure_column(conn, "topics", "created_at", "TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                topic_slug TEXT NOT NULL,
                agent TEXT NOT NULL,
                turn_no INTEGER NOT NULL,
                session_id TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_slug TEXT NOT NULL,
                speaker_type TEXT NOT NULL,
                speaker_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_states (
                topic_slug TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                session_id TEXT,
                last_read_message_id INTEGER,
                last_delivered_message_id INTEGER,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (topic_slug, agent_id)
            )
            """
        )
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()
