from __future__ import annotations

from .agent_state_service import ensure_agent_states, load_agent_states, update_agent_state


def load_sessions(slug: str) -> dict:
    ensure_agent_states(slug)
    agent_states = load_agent_states(slug)
    sessions: dict[str, dict] = {}
    for agent_id, state in agent_states.items():
        sessions[agent_id] = {
            "provider": "codex_cli" if agent_id == "codex" else "claude_cli",
            "session_id": state["session_id"],
            "status": state["status"],
            "last_used_at": state["updated_at"],
            "last_read_message_id": state["last_read_message_id"],
            "last_delivered_message_id": state["last_delivered_message_id"],
        }
    return sessions


def update_session(
    slug: str,
    agent: str,
    *,
    session_id: str | None = None,
    status: str | None = None,
    last_read_message_id: int | None = None,
    last_delivered_message_id: int | None = None,
) -> dict:
    update_agent_state(
        slug,
        agent,
        session_id=session_id,
        last_read_message_id=last_read_message_id,
        last_delivered_message_id=last_delivered_message_id,
        status=status,
    )
    return load_sessions(slug)

