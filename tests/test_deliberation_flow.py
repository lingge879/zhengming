from __future__ import annotations

import time
from pathlib import Path
import sys
from urllib.parse import unquote

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app
from app.db import get_conn
from app.schemas import AgentRunResult
from app.services import orchestrator
from app.services.agent_state_service import load_agent_states
from app.services.discussion_service import read_messages
from app.services.message_service import append_message
from app.services.state_service import load_state
from app.services.topic_service import create_topic, sync_topic_index
from app.services.workspace_service import (
    default_agents_doc,
    default_claude_doc,
    ensure_workspace_initialized,
    legacy_workspace_files,
    read_text,
    workspace_files,
    write_text,
)


def _unique_slug(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


def _cleanup_topic(slug: str) -> None:
    root = workspace_files(slug)["root"]
    if root.exists():
        import shutil

        shutil.rmtree(root)
    with get_conn() as conn:
        conn.execute("DELETE FROM agent_states WHERE topic_slug = ?", (slug,))
        conn.execute("DELETE FROM messages WHERE topic_slug = ?", (slug,))
        conn.execute("DELETE FROM topics WHERE slug = ?", (slug,))
        conn.commit()


def test_build_agent_prompt_uses_unread_messages_per_agent():
    slug = _unique_slug("unread-agent")
    try:
        create_topic("Unread Prompt", slug, "test")
        orchestrator.handle_user_message(slug, "u1")

        prompt, unread, delivered = orchestrator.build_agent_prompt(slug, "codex")
        assert [item["content"] for item in unread] == ["u1"]
        assert delivered == unread[-1]["id"]
        assert "u1" in prompt

        codex_msg = append_message(slug, "codex", "c1")
        from app.services.session_service import update_session

        update_session(
            slug,
            "codex",
            last_read_message_id=codex_msg["id"],
            last_delivered_message_id=codex_msg["id"],
            status="active",
        )
        append_message(slug, "user", "u2")

        _, codex_unread, _ = orchestrator.build_agent_prompt(slug, "codex")
        _, claude_unread, _ = orchestrator.build_agent_prompt(slug, "claudecode")
        assert [item["content"] for item in codex_unread] == ["u2"]
        assert [(item["speaker_id"], item["content"]) for item in claude_unread] == [
            ("user", "u1"),
            ("codex", "c1"),
            ("user", "u2"),
        ]
    finally:
        _cleanup_topic(slug)


def test_stream_full_round_advances_with_stub_agents(monkeypatch):
    slug = _unique_slug("round-stub")
    try:
        create_topic("Round Stub", slug, "test")

        def fake_stream_codex(**kwargs):
            yield {
                "type": "agent.event",
                "agent": "codex",
                "run_id": "codex-run",
                "session_id": "codex-session",
                "event_index": 1,
                "event": {"type": "turn.started"},
            }
            yield {
                "type": "run.completed",
                "agent": "codex",
                "run_id": "codex-run",
                "session_id": "codex-session",
                "event_count": 1,
                "message": "codex reply",
            }
            return AgentRunResult(
                agent="codex",
                run_id="codex-run",
                session_id="codex-session",
                message="codex reply",
                event_count=1,
            )

        def fake_stream_claude(**kwargs):
            yield {
                "type": "agent.event",
                "agent": "claudecode",
                "run_id": "claude-run",
                "session_id": "claude-session",
                "event_index": 1,
                "event": {"type": "assistant", "message": {"content": [{"type": "text", "text": "claude reply"}]}},
            }
            yield {
                "type": "run.completed",
                "agent": "claudecode",
                "run_id": "claude-run",
                "session_id": "claude-session",
                "event_count": 1,
                "message": "claude reply",
            }
            return AgentRunResult(
                agent="claudecode",
                run_id="claude-run",
                session_id="claude-session",
                message="claude reply",
                event_count=1,
            )

        monkeypatch.setattr(orchestrator, "stream_codex", fake_stream_codex)
        monkeypatch.setattr(orchestrator, "stream_claude", fake_stream_claude)

        packets = list(orchestrator.stream_full_round(slug, "hello", ["codex", "claudecode"]))
        assert any(packet["type"] == "orchestrator.completed" and packet["agent"] == "codex" for packet in packets)
        assert any(packet["type"] == "orchestrator.completed" and packet["agent"] == "claudecode" for packet in packets)

        messages = read_messages(slug)
        assert [item["speaker_id"] for item in messages] == ["user", "codex", "claudecode"]
        assert [item["content"] for item in messages] == ["hello", "codex reply", "claude reply"]

        state = load_state(slug)
        assert state["current_speaker"] == "user"

        agent_states = load_agent_states(slug)
        assert agent_states["codex"]["last_read_message_id"] == messages[1]["id"]
        assert agent_states["claudecode"]["last_read_message_id"] == messages[2]["id"]
    finally:
        _cleanup_topic(slug)


def test_run_agent_stream_endpoint_always_returns_snapshot(monkeypatch):
    slug = _unique_slug("stream-endpoint")
    try:
        create_topic("Run Agent Stream", slug, "test")
        orchestrator.handle_user_message(slug, "hello")

        def fake_stream_codex(**kwargs):
            yield {
                "type": "agent.event",
                "agent": "codex",
                "run_id": "codex-run",
                "session_id": "codex-session",
                "event_index": 1,
                "event": {"type": "turn.started"},
            }
            yield {
                "type": "run.completed",
                "agent": "codex",
                "run_id": "codex-run",
                "session_id": "codex-session",
                "event_count": 1,
                "message": "codex reply",
            }
            return AgentRunResult(
                agent="codex",
                run_id="codex-run",
                session_id="codex-session",
                message="codex reply",
                event_count=1,
            )

        monkeypatch.setattr(orchestrator, "stream_codex", fake_stream_codex)

        client = TestClient(app)
        response = client.post(f"/api/topics/{slug}/run-agent-stream", headers={"Accept": "application/x-ndjson"})
        assert response.status_code == 200
        lines = [line for line in response.text.splitlines() if line.strip()]
        assert '"type": "snapshot"' in lines[-1]
    finally:
        _cleanup_topic(slug)


def test_workspace_docs_are_migrated_away_from_discussion_md():
    slug = _unique_slug("workspace-migrate")
    try:
        create_topic("Workspace Migrate", slug, "test")
        files = workspace_files(slug)
        write_text(
            files["agents"],
            "# AGENTS\n\n3. 当前讨论记录统一写入 `discussion.md`。\n",
        )
        write_text(
            files["claude"],
            "# CLAUDE\n\n进入后先读取：\n\n- `discussion.md`\n",
        )

        ensure_workspace_initialized(slug)

        assert "discussion.md" not in read_text(files["agents"])
        assert "`messages`（数据库）" in read_text(files["claude"])
    finally:
        _cleanup_topic(slug)


def test_build_agent_prompt_is_minimal_and_contains_only_unread_messages():
    slug = _unique_slug("agent-prompt-minimal")
    try:
        create_topic("Agent Prompt Minimal", slug, "test")
        orchestrator.handle_user_message(slug, "hello")

        codex_prompt, _, _ = orchestrator.build_agent_prompt(slug, "codex")
        claude_prompt, _, _ = orchestrator.build_agent_prompt(slug, "claudecode")

        assert "[UNREAD_MESSAGES]" in codex_prompt
        assert "hello" in codex_prompt
        assert "AGENTS.md" not in codex_prompt
        assert "当前工作空间" not in codex_prompt
        assert "session_id" not in codex_prompt

        assert "[UNREAD_MESSAGES]" in claude_prompt
        assert "hello" in claude_prompt
        assert "CLAUDE.md" not in claude_prompt
    finally:
        _cleanup_topic(slug)


def test_legacy_workspace_files_are_removed_after_sync():
    slug = _unique_slug("legacy-cleanup")
    try:
        create_topic("Legacy Cleanup", slug, "test")
        legacy = legacy_workspace_files(slug)
        for path in legacy.values():
            path.write_text("legacy", encoding="utf-8")

        sync_topic_index(slug)

        assert all(not path.exists() for path in legacy.values())
    finally:
        _cleanup_topic(slug)


def test_start_session_creates_topic_and_first_message():
    client = TestClient(app)
    response = client.post(
        "/api/topics/start-session",
        data={"content": "这是新会话的第一句话"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/topics/")

    slug = unquote(location.removeprefix("/topics/"))
    try:
        messages = read_messages(slug)
        assert len(messages) == 1
        assert messages[0]["speaker_id"] == "user"
        assert messages[0]["content"] == "这是新会话的第一句话"
        state = load_state(slug)
        assert state["title"] == "这是新会话的第一句话"
        assert state["current_speaker"] == "codex"
    finally:
        _cleanup_topic(slug)


def test_start_session_respects_selected_agent_order():
    client = TestClient(app)
    response = client.post(
        "/api/topics/start-session",
        data={"content": "只让 claude 先回答", "agent_order": "claudecode"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    slug = unquote(response.headers["location"].removeprefix("/topics/"))
    try:
        state = load_state(slug)
        assert state["speaker_order"] == ["user", "claudecode"]
        assert state["current_speaker"] == "claudecode"
    finally:
        _cleanup_topic(slug)


def test_workspace_directory_uses_creation_timestamp_not_slug():
    slug = _unique_slug("timestamp-workspace")
    try:
        create_topic("Timestamp Workspace", slug, "test")
        root = workspace_files(slug)["root"]
        assert root.name != slug
        assert root.parent.name == "topics"
        assert len(root.name) >= 19
    finally:
        _cleanup_topic(slug)


def test_default_docs_are_loaded_from_defaults_directory():
    root = Path("/tmp/example-workspace")
    agents = default_agents_doc(root)
    claude = default_claude_doc(root)
    assert "# AGENTS" in agents
    assert "# CLAUDE" in claude
    assert "{{WORKSPACE_ROOT}}" not in agents
    assert "{{WORKSPACE_ROOT}}" not in claude
    assert str(root) in agents
    assert str(root) in claude
