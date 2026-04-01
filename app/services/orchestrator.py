from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock

from ..schemas import AgentRunResult
from .adapters.claude_adapter import run_claude, stream_claude
from .adapters.codex_adapter import run_codex, stream_codex
from .discussion_service import append_message
from .message_service import list_messages_after, list_messages_between
from .event_service import append_event
from .session_service import load_sessions, update_session
from .state_service import advance_speaker, load_state, save_state, set_speaker_order
from .topic_service import sync_topic_index
from .workspace_service import now_iso, workspace_files

logger = logging.getLogger("agent_deliberation.orchestrator")


_TOPIC_RUN_LOCKS: dict[str, Lock] = {}


def _get_topic_lock(slug: str) -> Lock:
    lock = _TOPIC_RUN_LOCKS.get(slug)
    if lock is None:
        lock = Lock()
        _TOPIC_RUN_LOCKS[slug] = lock
    return lock


@contextmanager
def topic_run_guard(slug: str):
    lock = _get_topic_lock(slug)
    acquired = lock.acquire(blocking=False)
    if not acquired:
        raise RuntimeError(f"topic {slug} 当前已有一条自动回复链路在运行，请等待其完成")
    try:
        yield
    finally:
        lock.release()


def _format_messages_for_prompt(messages: list[dict]) -> str:
    if not messages:
        return "（没有新的未读消息）"
    parts = []
    for message in messages:
        parts.append(
            f"""<message id="{message["id"]}" speaker="{message["speaker_id"]}" created_at="{message["created_at"]}">
{message["content"]}
</message>"""
        )
    return "\n\n".join(parts)


def build_agent_prompt(slug: str, agent: str) -> tuple[str, list[dict], int | None]:
    sessions = load_sessions(slug)
    session = sessions.get(agent, {})
    last_read = session.get("last_read_message_id")
    last_delivered = session.get("last_delivered_message_id")
    has_pending_delivery = last_delivered is not None and (last_read is None or last_delivered > last_read)
    if has_pending_delivery:
        unread_messages = list_messages_between(slug, last_read, last_delivered)
        delivered_upto = last_delivered
    else:
        unread_messages = list_messages_after(slug, last_read)
        delivered_upto = unread_messages[-1]["id"] if unread_messages else last_read
    prompt = f"""下面是你尚未读过的新消息。

请基于这些新消息继续当前讨论，直接给出你这一轮要发送的内容。

[UNREAD_MESSAGES]
{_format_messages_for_prompt(unread_messages)}
"""
    return prompt, unread_messages, delivered_upto


def run_current_agent(slug: str) -> AgentRunResult:
    state = load_state(slug)
    agent = state["current_speaker"]
    if agent not in {"codex", "claudecode"}:
        raise ValueError(f"当前 speaker 不是 agent: {agent}")

    files = workspace_files(slug)
    sessions = load_sessions(slug)
    session_id = sessions.get(agent, {}).get("session_id")
    update_session(slug, agent, status="running")

    prompt, _, delivered_upto = build_agent_prompt(slug, agent)
    update_session(slug, agent, last_delivered_message_id=delivered_upto, status="running")
    try:
        if agent == "codex":
            result = run_codex(slug=slug, workspace=files["root"], prompt=prompt, session_id=session_id)
        else:
            result = run_claude(slug=slug, workspace=files["root"], prompt=prompt, session_id=session_id)
    except Exception:
        update_session(slug, agent, session_id=session_id, status="error")
        sync_topic_index(slug)
        raise

    appended = append_message(slug, agent, result.message or "(空回复)")
    state = load_state(slug)
    state["last_message_id"] = appended["id"]
    save_state(slug, state)
    update_session(
        slug,
        agent,
        session_id=result.session_id,
        last_read_message_id=appended["id"],
        last_delivered_message_id=appended["id"],
        status="active",
    )
    append_event(
        slug,
        {
            "topic_slug": slug,
            "run_id": result.run_id,
            "agent": agent,
            "source": "orchestrator",
            "ts": now_iso(),
            "summary": {
                "event_count": result.event_count,
                "session_id": result.session_id,
                "message_length": len(result.message or ""),
            },
        },
    )
    advance_speaker(slug)
    sync_topic_index(slug)
    return result


def stream_current_agent(slug: str) -> Iterator[dict]:
    state = load_state(slug)
    agent = state["current_speaker"]
    if agent not in {"codex", "claudecode"}:
        raise ValueError(f"当前 speaker 不是 agent: {agent}")

    files = workspace_files(slug)
    sessions = load_sessions(slug)
    session_id = sessions.get(agent, {}).get("session_id")
    update_session(slug, agent, status="running")

    yield {
        "type": "orchestrator.started",
        "agent": agent,
        "current_speaker": agent,
        "turn_no": state["turn_no"],
        "session_id": session_id,
    }
    logger.info("[%s] orchestrator.started agent=%s turn=%s session=%s", slug, agent, state["turn_no"], session_id)

    prompt, _, delivered_upto = build_agent_prompt(slug, agent)
    logger.info("[%s] >>> PROMPT to %s:\n%s", slug, agent, prompt)
    update_session(slug, agent, last_delivered_message_id=delivered_upto, status="running")
    iterator = (
        stream_codex(slug=slug, workspace=files["root"], prompt=prompt, session_id=session_id)
        if agent == "codex"
        else stream_claude(slug=slug, workspace=files["root"], prompt=prompt, session_id=session_id)
    )

    result: AgentRunResult | None = None
    try:
        while True:
            packet = next(iterator)
            yield packet
    except StopIteration as stop:
        result = stop.value
    except Exception:
        update_session(slug, agent, session_id=session_id, status="error")
        sync_topic_index(slug)
        raise

    if result is None:
        update_session(slug, agent, status="error")
        raise RuntimeError(f"{agent} 未返回完成结果")

    appended = append_message(slug, agent, result.message or "(空回复)")
    state = load_state(slug)
    state["last_message_id"] = appended["id"]
    save_state(slug, state)
    update_session(
        slug,
        agent,
        session_id=result.session_id,
        last_read_message_id=appended["id"],
        last_delivered_message_id=appended["id"],
        status="active",
    )
    append_event(
        slug,
        {
            "topic_slug": slug,
            "run_id": result.run_id,
            "agent": agent,
            "source": "orchestrator",
            "ts": now_iso(),
            "summary": {
                "event_count": result.event_count,
                "session_id": result.session_id,
                "message_length": len(result.message or ""),
            },
        },
    )
    state = advance_speaker(slug)
    sync_topic_index(slug)
    logger.info("[%s] orchestrator.completed agent=%s message_len=%d next=%s", slug, agent, len(result.message or ""), state["current_speaker"])
    yield {
        "type": "orchestrator.completed",
        "agent": agent,
        "run_id": result.run_id,
        "session_id": result.session_id,
        "next_speaker": state["current_speaker"],
        "turn_no": state["turn_no"],
        "message": result.message,
    }


def handle_user_message(slug: str, content: str) -> None:
    state = load_state(slug)
    if state["current_speaker"] != "user":
        raise ValueError("当前不是 user 发言")
    appended = append_message(slug, "user", content)
    state["last_message_id"] = appended["id"]
    save_state(slug, state)
    advance_speaker(slug)
    sync_topic_index(slug)


def stream_full_round(slug: str, content: str, agent_order: list[str]) -> Iterator[dict]:
    with topic_run_guard(slug):
        normalized = [agent for agent in agent_order if agent in {"codex", "claudecode"}]
        if not normalized or normalized != list(dict.fromkeys(normalized)):
            raise ValueError("agent 顺序必须是去重后的 codex/claudecode 非空子集")

        state = set_speaker_order(slug, normalized)
        sync_topic_index(slug)
        yield {
            "type": "round.started",
            "turn_no": state["turn_no"],
            "agent_order": normalized,
        }

        handle_user_message(slug, content)
        user_state = load_state(slug)
        yield {
            "type": "user.message.accepted",
            "next_speaker": user_state["current_speaker"],
            "turn_no": user_state["turn_no"],
            "content": content,
        }

        while load_state(slug)["current_speaker"] != "user":
            for packet in stream_current_agent(slug):
                yield packet


def stream_continue_round(slug: str) -> Iterator[dict]:
    with topic_run_guard(slug):
        state = load_state(slug)
        if state["current_speaker"] == "user":
            yield {
                "type": "round.idle",
                "turn_no": state["turn_no"],
                "message": "当前没有待继续的 agent 轮次",
            }
            return

        yield {
            "type": "round.resume",
            "turn_no": state["turn_no"],
            "current_speaker": state["current_speaker"],
        }
        while load_state(slug)["current_speaker"] != "user":
            for packet in stream_current_agent(slug):
                yield packet
