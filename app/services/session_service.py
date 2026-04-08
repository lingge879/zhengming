from __future__ import annotations

from .agent_state_service import ensure_agent_states, load_agent_states, update_agent_state
from .state_service import load_state


def _normalize_agent_status(
    *,
    agent_id: str,
    raw_status: str | None,
    current_speaker: str,
) -> str:
    status = str(raw_status or "").strip() or "idle"

    if status == "active":
        status = "idle"

    if agent_id == current_speaker and status not in {"running", "error"}:
        return "pending"

    if agent_id != current_speaker and status == "pending":
        return "idle"

    return status


def load_sessions(slug: str) -> dict:
    ensure_agent_states(slug)
    agent_states = load_agent_states(slug)
    state = load_state(slug)
    current_speaker = str(state.get("current_speaker") or "").strip()
    sessions: dict[str, dict] = {}
    for agent_id, state in agent_states.items():
        normalized_status = _normalize_agent_status(
            agent_id=agent_id,
            raw_status=state["status"],
            current_speaker=current_speaker,
        )
        sessions[agent_id] = {
            "provider": "codex_cli" if agent_id == "codex" else "claude_cli",
            "session_id": state["session_id"],
            "status": normalized_status,
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
