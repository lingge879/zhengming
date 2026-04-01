from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

from ...schemas import AgentRunResult
from ..event_service import append_event
from ..workspace_service import now_iso

logger = logging.getLogger("agent_deliberation.codex")


def _extract_thread_id(event: dict) -> str | None:
    return event.get("thread_id")


def _extract_agent_text(event: dict) -> str | None:
    item = event.get("item", {})
    if isinstance(item, dict) and item.get("type") == "agent_message":
        return item.get("text")
    return None


def stream_codex(
    *,
    slug: str,
    workspace: Path,
    prompt: str,
    session_id: str | None,
) -> Iterator[dict]:
    run_id = f"codex-{uuid.uuid4().hex[:12]}"
    final_text = ""
    event_count = 0
    thread_id = session_id

    with tempfile.NamedTemporaryFile(prefix="codex-last-", suffix=".txt", delete=False) as tmp:
        output_path = Path(tmp.name)

    cmd = [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--sandbox",
        "danger-full-access",
        "--cd",
        str(workspace),
        "-c",
        'approval_policy="never"',
        "-o",
        str(output_path),
    ]
    if session_id:
        cmd.extend(["resume", session_id])

    logger.info("[codex] run_id=%s cmd=%s cwd=%s", run_id, " ".join(cmd), workspace)

    yield {
        "type": "run.started",
        "agent": "codex",
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
            thread_id = _extract_thread_id(event) or thread_id
            final_text = _extract_agent_text(event) or final_text
            stored = {
                "topic_slug": slug,
                "run_id": run_id,
                "agent": "codex",
                "turn_no": None,
                "source": "codex_cli",
                "ts": now_iso(),
                "event": event,
            }
            append_event(slug, stored)
            packet = {
                "type": "agent.event",
                "agent": "codex",
                "run_id": run_id,
                "session_id": thread_id,
                "event_index": event_count,
                "event": event,
            }
        except json.JSONDecodeError:
            stored = {
                "topic_slug": slug,
                "run_id": run_id,
                "agent": "codex",
                "ts": now_iso(),
                "source": "codex_cli",
                "raw_line": raw,
            }
            append_event(slug, stored)
            packet = {
                "type": "agent.raw_line",
                "agent": "codex",
                "run_id": run_id,
                "session_id": thread_id,
                "event_index": event_count,
                "raw_line": raw,
            }
        yield packet

    stderr = process.stderr.read() if process.stderr else ""
    exit_code = process.wait()

    if output_path.exists():
        text = output_path.read_text(encoding="utf-8").strip()
        if text:
            final_text = text
        output_path.unlink(missing_ok=True)

    if exit_code != 0:
        raise RuntimeError(f"codex 运行失败: {stderr.strip() or f'exit={exit_code}'}")

    result = AgentRunResult(
        agent="codex",
        run_id=run_id,
        session_id=thread_id,
        message=final_text.strip(),
        event_count=event_count,
        raw={"stderr": stderr.strip()},
    )
    yield {
        "type": "run.completed",
        "agent": "codex",
        "run_id": run_id,
        "session_id": thread_id,
        "event_count": event_count,
        "message": result.message,
    }
    return result


def run_codex(*, slug: str, workspace: Path, prompt: str, session_id: str | None) -> AgentRunResult:
    iterator = stream_codex(slug=slug, workspace=workspace, prompt=prompt, session_id=session_id)
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
        raise RuntimeError("codex 未返回完成结果")
    return AgentRunResult(
        agent="codex",
        run_id=last_completed["run_id"],
        session_id=last_completed.get("session_id"),
        message=last_completed.get("message", ""),
        event_count=last_completed.get("event_count", 0),
    )
