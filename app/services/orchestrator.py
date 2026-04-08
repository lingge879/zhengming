from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timedelta
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock

from ..schemas import AgentRunResult
from .adapters.claude_adapter import run_claude, stream_claude
from .adapters.codex_adapter import run_codex, stream_codex
from .discussion_service import append_message
from .message_service import last_speaker_id, list_messages_after, list_messages_between
from .event_service import append_event
from .prompt_delivery_service import create_prompt_delivery, update_prompt_delivery
from .session_service import load_sessions, update_session
from .state_service import advance_speaker, load_state, save_state, set_speaker_order
from .topic_service import sync_topic_index
from .workspace_service import now_iso, workspace_files

logger = logging.getLogger("agent_deliberation.orchestrator")


_TOPIC_RUN_LOCKS: dict[str, Lock] = {}
_TOPIC_CANCEL_FLAGS: dict[str, bool] = {}
_TOPIC_PROCESSES: dict[str, subprocess.Popen] = {}
_ORPHANED_RUN_GRACE_SECONDS = 15


class CancelledError(Exception):
    pass


def _set_pending_agent(slug: str, agent: str | None) -> None:
    sessions = load_sessions(slug)
    for agent_id in ("codex", "claudecode"):
        if agent_id == agent:
            update_session(slug, agent_id, status="pending")
        else:
            current_status = sessions.get(agent_id, {}).get("status")
            if current_status not in {"running", "error"}:
                update_session(slug, agent_id, status="idle")


def _sync_agent_states_after_turn(slug: str, current_speaker: str) -> None:
    next_agent = current_speaker if current_speaker in {"codex", "claudecode"} else None
    _set_pending_agent(slug, next_agent)


def _get_topic_lock(slug: str) -> Lock:
    lock = _TOPIC_RUN_LOCKS.get(slug)
    if lock is None:
        lock = Lock()
        _TOPIC_RUN_LOCKS[slug] = lock
    return lock


def register_process(slug: str, process: subprocess.Popen) -> None:
    _TOPIC_PROCESSES[slug] = process


def unregister_process(slug: str) -> None:
    _TOPIC_PROCESSES.pop(slug, None)


def reconcile_orphaned_run(slug: str) -> bool:
    state = load_state(slug)
    if state["current_speaker"] == "user":
        return False

    sessions = load_sessions(slug)
    agent = state["current_speaker"]
    session = sessions.get(agent, {})
    if session.get("status") != "running":
        return False

    proc = _TOPIC_PROCESSES.get(slug)
    if proc is not None and proc.poll() is None:
        return False
    if proc is not None and proc.poll() is not None:
        unregister_process(slug)

    last_used_at = session.get("last_used_at")
    if not last_used_at:
        return False
    try:
        last_seen = datetime.fromisoformat(last_used_at)
    except ValueError:
        return False
    if datetime.now(last_seen.tzinfo) - last_seen < timedelta(seconds=_ORPHANED_RUN_GRACE_SECONDS):
        return False

    logger.warning("[%s] recovering orphaned run for agent=%s", slug, agent)
    update_session(slug, agent, status="error")
    state["current_speaker"] = "user"
    save_state(slug, state)
    append_event(
        slug,
        {
            "type": "error",
            "agent": agent,
            "message": "检测到已失联的后台任务，已自动回收运行状态",
            "ts": now_iso(),
        },
    )
    sync_topic_index(slug)
    return True


def cancel_topic(slug: str) -> None:
    logger.info("[%s] cancel requested", slug)
    _TOPIC_CANCEL_FLAGS[slug] = True
    proc = _TOPIC_PROCESSES.pop(slug, None)
    if proc and proc.poll() is None:
        logger.info("[%s] killing subprocess pid=%s", slug, proc.pid)
        proc.kill()


def _check_cancelled(slug: str) -> None:
    if _TOPIC_CANCEL_FLAGS.get(slug):
        raise CancelledError(f"topic {slug} cancelled")


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
        pending_messages = list_messages_between(slug, last_read, last_delivered)
        newer_messages = list_messages_after(slug, last_delivered)
        unread_messages = pending_messages + newer_messages
        delivered_upto = unread_messages[-1]["id"] if unread_messages else last_delivered
    else:
        unread_messages = list_messages_after(slug, last_read)
        delivered_upto = unread_messages[-1]["id"] if unread_messages else last_read
    logger.info(
        "[%s] prompt window agent=%s last_read=%s last_delivered=%s has_pending=%s unread_ids=%s delivered_upto=%s",
        slug,
        agent,
        last_read,
        last_delivered,
        has_pending_delivery,
        [message["id"] for message in unread_messages],
        delivered_upto,
    )
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
    session = sessions.get(agent, {})
    session_id = session.get("session_id")
    update_session(slug, agent, status="running")

    prompt, unread_messages, delivered_upto = build_agent_prompt(slug, agent)
    delivery = create_prompt_delivery(
        slug,
        agent,
        run_id=None,
        session_id=session_id,
        turn_no=state["turn_no"],
        last_read_before=session.get("last_read_message_id"),
        last_delivered_before=session.get("last_delivered_message_id"),
        delivered_upto=delivered_upto,
        message_ids=[message["id"] for message in unread_messages],
        status="sent",
    )
    update_session(slug, agent, last_delivered_message_id=delivered_upto, status="running")
    try:
        if agent == "codex":
            result = run_codex(slug=slug, workspace=files["root"], prompt=prompt, session_id=session_id)
        else:
            result = run_claude(slug=slug, workspace=files["root"], prompt=prompt, session_id=session_id)
    except Exception:
        update_prompt_delivery(delivery["id"], status="failed")
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
        status="idle",
    )
    update_prompt_delivery(
        delivery["id"],
        run_id=result.run_id,
        session_id=result.session_id,
        status="completed",
        delivered_upto=delivered_upto,
        response_message_id=appended["id"],
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
    next_state = load_state(slug)
    _sync_agent_states_after_turn(slug, next_state["current_speaker"])
    sync_topic_index(slug)
    return result


def stream_current_agent(slug: str) -> Iterator[dict]:
    state = load_state(slug)
    agent = state["current_speaker"]
    if agent not in {"codex", "claudecode"}:
        raise ValueError(f"当前 speaker 不是 agent: {agent}")

    files = workspace_files(slug)
    sessions = load_sessions(slug)
    session = sessions.get(agent, {})
    session_id = session.get("session_id")
    update_session(slug, agent, status="running")

    yield {
        "type": "orchestrator.started",
        "agent": agent,
        "current_speaker": agent,
        "turn_no": state["turn_no"],
        "session_id": session_id,
    }
    append_event(
        slug,
        {
            "type": "orchestrator.started",
            "agent": agent,
            "current_speaker": agent,
            "turn_no": state["turn_no"],
            "session_id": session_id,
            "ts": now_iso(),
        },
    )
    logger.info("[%s] orchestrator.started agent=%s turn=%s session=%s", slug, agent, state["turn_no"], session_id)

    prompt, unread_messages, delivered_upto = build_agent_prompt(slug, agent)
    logger.info("[%s] >>> PROMPT to %s:\n%s", slug, agent, prompt)
    delivery = create_prompt_delivery(
        slug,
        agent,
        run_id=None,
        session_id=session_id,
        turn_no=state["turn_no"],
        last_read_before=session.get("last_read_message_id"),
        last_delivered_before=session.get("last_delivered_message_id"),
        delivered_upto=delivered_upto,
        message_ids=[message["id"] for message in unread_messages],
        status="sent",
    )
    update_session(slug, agent, last_delivered_message_id=delivered_upto, status="running")
    _on_proc = lambda proc: register_process(slug, proc)
    iterator = (
        stream_codex(slug=slug, workspace=files["root"], prompt=prompt, session_id=session_id, on_process=_on_proc)
        if agent == "codex"
        else stream_claude(slug=slug, workspace=files["root"], prompt=prompt, session_id=session_id, on_process=_on_proc)
    )

    result: AgentRunResult | None = None
    _TOPIC_CANCEL_FLAGS.pop(slug, None)  # clear any stale flag
    try:
        while True:
            _check_cancelled(slug)
            packet = next(iterator)
            yield packet
    except StopIteration as stop:
        result = stop.value
    except CancelledError:
        update_prompt_delivery(delivery["id"], status="cancelled")
        update_session(slug, agent, session_id=session_id, status="idle")
        sync_topic_index(slug)
        raise
    except Exception:
        update_prompt_delivery(delivery["id"], status="failed")
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
        status="idle",
    )
    update_prompt_delivery(
        delivery["id"],
        run_id=result.run_id,
        session_id=result.session_id,
        status="completed",
        delivered_upto=delivered_upto,
        response_message_id=appended["id"],
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
    _sync_agent_states_after_turn(slug, state["current_speaker"])
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
    append_event(
        slug,
        {
            "type": "orchestrator.completed",
            "agent": agent,
            "run_id": result.run_id,
            "session_id": result.session_id,
            "next_speaker": state["current_speaker"],
            "turn_no": state["turn_no"],
            "message": result.message,
            "ts": now_iso(),
        },
    )


def handle_user_message(slug: str, content: str) -> None:
    state = load_state(slug)
    if state["current_speaker"] != "user":
        raise ValueError("当前不是 user 发言")
    appended = append_message(slug, "user", content)
    state["last_message_id"] = appended["id"]
    save_state(slug, state)
    append_event(
        slug,
        {
            "type": "user.message",
            "message_id": appended["id"],
            "content": content,
            "ts": now_iso(),
        },
    )
    advance_speaker(slug)
    next_state = load_state(slug)
    _sync_agent_states_after_turn(slug, next_state["current_speaker"])
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

        try:
            while load_state(slug)["current_speaker"] != "user":
                for packet in stream_current_agent(slug):
                    yield packet
        except CancelledError:
            logger.info("[%s] round cancelled", slug)
            state = load_state(slug)
            state["current_speaker"] = "user"
            save_state(slug, state)
            _sync_agent_states_after_turn(slug, state["current_speaker"])
            sync_topic_index(slug)
            _TOPIC_CANCEL_FLAGS.pop(slug, None)
            yield {"type": "round.cancelled", "message": "已取消"}
        except Exception as exc:
            logger.error("[%s] round failed: %s", slug, exc)
            unregister_process(slug)
            state = load_state(slug)
            state["current_speaker"] = "user"
            save_state(slug, state)
            _sync_agent_states_after_turn(slug, state["current_speaker"])
            sync_topic_index(slug)
            yield {"type": "error", "message": str(exc)}


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
        try:
            while load_state(slug)["current_speaker"] != "user":
                for packet in stream_current_agent(slug):
                    yield packet
        except CancelledError:
            logger.info("[%s] continue cancelled", slug)
            state = load_state(slug)
            state["current_speaker"] = "user"
            save_state(slug, state)
            _sync_agent_states_after_turn(slug, state["current_speaker"])
            sync_topic_index(slug)
            _TOPIC_CANCEL_FLAGS.pop(slug, None)
            yield {"type": "round.cancelled", "message": "已取消"}
        except Exception as exc:
            logger.error("[%s] continue failed: %s", slug, exc)
            unregister_process(slug)
            state = load_state(slug)
            state["current_speaker"] = "user"
            save_state(slug, state)
            _sync_agent_states_after_turn(slug, state["current_speaker"])
            sync_topic_index(slug)
            yield {"type": "error", "message": str(exc)}


def stream_nudge_agent(slug: str, agent: str) -> Iterator[dict]:
    """Let a specific agent speak without a new user message.

    The target agent must NOT be the last speaker in the discussion.
    After the agent finishes, current_speaker is reset to 'user'.
    """
    if agent not in {"codex", "claudecode"}:
        raise ValueError(f"无效的 agent: {agent}")

    last_speaker = last_speaker_id(slug)
    if last_speaker == agent:
        raise ValueError(f"{agent} 是最后一个发言者，不能连续指定同一个 agent 继续发言")

    with topic_run_guard(slug):
        # Temporarily set current_speaker so stream_current_agent picks it up
        state = load_state(slug)
        state["current_speaker"] = agent
        save_state(slug, state)
        sync_topic_index(slug)

        yield {"type": "nudge.started", "agent": agent}

        try:
            for packet in stream_current_agent(slug):
                yield packet
        except CancelledError:
            logger.info("[%s] nudge cancelled for %s", slug, agent)
            state = load_state(slug)
            state["current_speaker"] = "user"
            save_state(slug, state)
            _sync_agent_states_after_turn(slug, state["current_speaker"])
            sync_topic_index(slug)
            _TOPIC_CANCEL_FLAGS.pop(slug, None)
            yield {"type": "round.cancelled", "message": "已取消"}
            return
        except Exception as exc:
            logger.error("[%s] nudge failed for %s: %s", slug, agent, exc)
            unregister_process(slug)
            state = load_state(slug)
            state["current_speaker"] = "user"
            save_state(slug, state)
            _sync_agent_states_after_turn(slug, state["current_speaker"])
            sync_topic_index(slug)
            yield {"type": "error", "message": str(exc)}
            return

        # Reset to user after nudge (stream_current_agent called advance_speaker,
        # which may have moved to the wrong next speaker)
        state = load_state(slug)
        state["current_speaker"] = "user"
        save_state(slug, state)
        _sync_agent_states_after_turn(slug, state["current_speaker"])
        sync_topic_index(slug)
