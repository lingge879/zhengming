from __future__ import annotations

import json
import logging
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

from ...schemas import AgentRunResult
from ..event_service import append_event
from ..workspace_service import now_iso

logger = logging.getLogger("agent_deliberation.claude")


def _extract_claude_message(event: dict) -> str | None:
    event_type = event.get("type")
    if event_type == "assistant":
        message = event.get("message", {})
        content = message.get("content", [])
        texts = []
        for item in content:
            if item.get("type") == "text":
                texts.append(item.get("text", ""))
        text = "".join(texts).strip()
        return text or None
    if event_type == "result":
        result = event.get("result")
        if isinstance(result, str):
            return result.strip() or None
    return None


def _extract_session_id(event: dict) -> str | None:
    return event.get("session_id")


def stream_claude(
    *,
    slug: str,
    workspace: Path,
    prompt: str,
    session_id: str | None,
) -> Iterator[dict]:
    run_id = f"claude-{uuid.uuid4().hex[:12]}"
    final_text = ""
    assistant_text = ""
    event_count = 0
    current_session_id = session_id

    cmd = [
        "claude",
        "-p",
        "--verbose",
        "--dangerously-skip-permissions",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
    ]
    if session_id:
        cmd.extend(["--resume", session_id])

    logger.info("[claude] run_id=%s cmd=%s cwd=%s", run_id, " ".join(cmd), workspace)

    yield {
        "type": "run.started",
        "agent": "claudecode",
        "run_id": run_id,
        "session_id": session_id,
        "cmd": cmd,
    }

    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=workspace,
        bufsize=1,
    )

    assert process.stdin is not None
    process.stdin.write(prompt)
    process.stdin.close()

    assert process.stdout is not None
    for line in process.stdout:
        raw = line.rstrip("\n")
        if not raw.strip():
            continue
        event_count += 1
        packet: dict
        try:
            event = json.loads(raw)
            current_session_id = _extract_session_id(event) or current_session_id
            extracted = _extract_claude_message(event)
            if event.get("type") == "assistant" and extracted:
                assistant_text = extracted
            elif extracted:
                final_text = extracted
            stored = {
                "topic_slug": slug,
                "run_id": run_id,
                "agent": "claudecode",
                "turn_no": None,
                "source": "claude_cli",
                "ts": now_iso(),
                "event": event,
            }
            append_event(slug, stored)
            packet = {
                "type": "agent.event",
                "agent": "claudecode",
                "run_id": run_id,
                "session_id": current_session_id,
                "event_index": event_count,
                "event": event,
            }
        except json.JSONDecodeError:
            stored = {
                "topic_slug": slug,
                "run_id": run_id,
                "agent": "claudecode",
                "ts": now_iso(),
                "source": "claude_cli",
                "raw_line": raw,
            }
            append_event(slug, stored)
            packet = {
                "type": "agent.raw_line",
                "agent": "claudecode",
                "run_id": run_id,
                "session_id": current_session_id,
                "event_index": event_count,
                "raw_line": raw,
            }
        yield packet

    stderr = process.stderr.read() if process.stderr else ""
    exit_code = process.wait()
    if exit_code != 0:
        raise RuntimeError(f"claude 运行失败: {stderr.strip() or f'exit={exit_code}'}")

    preferred_text = assistant_text or final_text
    result = AgentRunResult(
        agent="claudecode",
        run_id=run_id,
        session_id=current_session_id,
        message=preferred_text.strip(),
        event_count=event_count,
        raw={"stderr": stderr.strip()},
    )
    yield {
        "type": "run.completed",
        "agent": "claudecode",
        "run_id": run_id,
        "session_id": current_session_id,
        "event_count": event_count,
        "message": result.message,
    }
    return result


def run_claude(*, slug: str, workspace: Path, prompt: str, session_id: str | None) -> AgentRunResult:
    iterator = stream_claude(slug=slug, workspace=workspace, prompt=prompt, session_id=session_id)
    last_completed: dict | None = None
    try:
        while True:
            packet = next(iterator)
            if packet.get("type") == "run.completed":
                last_completed = packet
    except StopIteration as stop:
        if stop.value:
            return stop.value
    if last_completed is None:
        raise RuntimeError("claude 未返回完成结果")
    return AgentRunResult(
        agent="claudecode",
        run_id=last_completed["run_id"],
        session_id=last_completed.get("session_id"),
        message=last_completed.get("message", ""),
        event_count=last_completed.get("event_count", 0),
    )
