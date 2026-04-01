from __future__ import annotations

import json
from pathlib import Path

from ..config import DEFAULT_AGENT_LIST, DEFAULT_SPEAKER_ORDER, LEGACY_TOPICS_DIR, WORKSPACES_DIR
from ..db import get_conn
from .agent_state_service import ensure_agent_states
from .message_service import latest_message_id
from .state_service import load_state
from .workspace_service import (
    create_topic_workspace,
    ensure_workspace_initialized,
    legacy_workspace_files,
    now_iso,
    remove_legacy_workspace_files,
    topic_path,
    workspace_files,
)


def _read_legacy_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_topic_row(slug: str) -> None:
    files = workspace_files(slug)
    legacy = legacy_workspace_files(slug)
    with get_conn() as conn:
        existing = conn.execute("SELECT slug FROM topics WHERE slug = ?", (slug,)).fetchone()
        if existing is not None:
            return

        state_payload = _read_legacy_json(legacy["state"])
        config_payload = _read_legacy_json(legacy["config"])
        title = state_payload.get("title") or config_payload.get("title") or slug
        created_at = state_payload.get("created_at") or config_payload.get("created_at") or now_iso()
        updated_at = state_payload.get("updated_at") or created_at
        conn.execute(
            """
            INSERT INTO topics (
                slug, title, description, status, turn_no, speaker_order, current_speaker,
                last_message_id, created_at, updated_at, workspace_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug,
                title,
                config_payload.get("description", ""),
                state_payload.get("status", "active"),
                state_payload.get("turn_no", 1),
                json.dumps(state_payload.get("speaker_order", DEFAULT_SPEAKER_ORDER), ensure_ascii=False),
                state_payload.get("current_speaker", "user"),
                state_payload.get("last_message_id", latest_message_id(slug)),
                created_at,
                updated_at,
                str(files["root"]),
            ),
        )
        conn.commit()


def create_topic(title: str, slug: str, description: str) -> Path:
    root = create_topic_workspace(title=title, slug=slug, description=description)
    ts = now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO topics (
                slug, title, description, status, turn_no, speaker_order, current_speaker,
                last_message_id, created_at, updated_at, workspace_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug,
                title,
                description,
                "active",
                1,
                json.dumps(DEFAULT_SPEAKER_ORDER, ensure_ascii=False),
                "user",
                None,
                ts,
                ts,
                str(root),
            ),
        )
        conn.commit()
    sync_topic_index(slug)
    return root


def sync_topic_index(slug: str) -> None:
    ensure_workspace_initialized(slug)
    ensure_agent_states(slug)
    _ensure_topic_row(slug)
    state = load_state(slug)
    files = workspace_files(slug)
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE topics
            SET title = ?, status = ?, turn_no = ?, speaker_order = ?, current_speaker = ?,
                last_message_id = ?, updated_at = ?, workspace_path = ?
            WHERE slug = ?
            """,
            (
                state["title"],
                state["status"],
                state["turn_no"],
                json.dumps(state["speaker_order"], ensure_ascii=False),
                state["current_speaker"],
                latest_message_id(slug),
                state["updated_at"],
                str(files["root"]),
                slug,
            ),
        )
        conn.commit()
    remove_legacy_workspace_files(slug)


def sync_all_topics() -> None:
    WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
    LEGACY_TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        rows = conn.execute("SELECT slug, workspace_path FROM topics").fetchall()

    seen_legacy_slugs = {row["slug"] for row in rows}
    known_workspace_paths = {
        str((Path(row["workspace_path"]) if row["workspace_path"] else topic_path(row["slug"])).resolve())
        for row in rows
    }
    for row in rows:
        slug = row["slug"]
        workspace_path = Path(row["workspace_path"]) if row["workspace_path"] else topic_path(slug)
        if workspace_path.exists():
            sync_topic_index(slug)
            continue
        with get_conn() as conn:
            conn.execute("DELETE FROM topics WHERE slug = ?", (slug,))
            conn.execute("DELETE FROM agent_states WHERE topic_slug = ?", (slug,))
            conn.execute("DELETE FROM messages WHERE topic_slug = ?", (slug,))
            conn.commit()

    for base_dir in (WORKSPACES_DIR, LEGACY_TOPICS_DIR):
        for child in base_dir.iterdir():
            if (
                child.is_dir()
                and child.name not in seen_legacy_slugs
                and str(child.resolve()) not in known_workspace_paths
            ):
                if (child / "AGENTS.md").exists() or (child / "CLAUDE.md").exists():
                    sync_topic_index(child.name)


def list_topics() -> list[dict]:
    sync_all_topics()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT slug, title, description, status, turn_no, current_speaker, updated_at, workspace_path
            FROM topics
            ORDER BY updated_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_topic(slug: str) -> dict:
    ensure_workspace_initialized(slug)
    if not topic_path(slug).exists():
        raise FileNotFoundError(slug)
    _ensure_topic_row(slug)
    state = load_state(slug)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT description, created_at FROM topics WHERE slug = ?",
            (slug,),
        ).fetchone()
    return {
        "slug": slug,
        "root": str(workspace_files(slug)["root"]),
        "state": state,
        "config": {
            "slug": slug,
            "title": state["title"],
            "description": row["description"] if row else "",
            "speaker_order": state["speaker_order"],
            "agents": DEFAULT_AGENT_LIST,
            "created_at": row["created_at"] if row else state["created_at"],
        },
    }
