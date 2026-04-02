from __future__ import annotations

import json
import threading
from queue import Queue

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse

from ..services.discussion_service import read_messages
from ..services.event_service import read_events
from ..services.orchestrator import (
    cancel_topic,
    handle_user_message,
    run_current_agent,
    stream_continue_round,
    stream_current_agent,
    stream_full_round,
    stream_nudge_agent,
)
from ..services.prompt_delivery_service import list_prompt_deliveries
from ..services.session_service import load_sessions
from ..services.state_service import load_state


router = APIRouter(prefix="/api/topics/{slug}", tags=["turns"])

_SENTINEL = object()


def _run_generator_in_background(gen, slug):
    """Run a generator in a background thread, pushing packets to a queue.
    The generator runs to completion regardless of whether the client disconnects."""
    q = Queue(maxsize=256)

    def _worker():
        try:
            for packet in gen:
                q.put(json.dumps(packet, ensure_ascii=False) + "\n")
        except Exception as exc:
            q.put(json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n")
        # Always send final snapshot
        try:
            snapshot = {
                "type": "snapshot",
                "state": load_state(slug),
                "sessions": load_sessions(slug),
                "messages": read_messages(slug),
                "events": read_events(slug),
                "prompt_deliveries": list_prompt_deliveries(slug),
            }
            q.put(json.dumps(snapshot, ensure_ascii=False) + "\n")
        except Exception:
            pass
        q.put(_SENTINEL)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    def _stream():
        while True:
            item = q.get()
            if item is _SENTINEL:
                break
            yield item

    return _stream()


@router.post("/messages")
def post_user_message(slug: str, content: str = Form(...)):
    try:
        handle_user_message(slug, content.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/topics/{slug}", status_code=303)


@router.post("/messages-json")
def post_user_message_json(slug: str, content: str = Form(...)):
    try:
        handle_user_message(slug, content.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "state": load_state(slug),
        "sessions": load_sessions(slug),
        "messages": read_messages(slug),
    }


@router.post("/run-agent")
def run_agent_turn(slug: str):
    try:
        run_current_agent(slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/topics/{slug}", status_code=303)


@router.post("/run-agent-stream")
def run_agent_turn_stream(slug: str):
    def event_stream():
        try:
            for packet in stream_current_agent(slug):
                yield json.dumps(packet, ensure_ascii=False) + "\n"
        except ValueError as exc:
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"
        snapshot = {
            "type": "snapshot",
            "state": load_state(slug),
            "sessions": load_sessions(slug),
            "messages": read_messages(slug),
            "events": read_events(slug),
            "prompt_deliveries": list_prompt_deliveries(slug),
        }
        yield json.dumps(snapshot, ensure_ascii=False) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/cancel")
def cancel_round(slug: str):
    try:
        cancel_topic(slug)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True}

@router.get("/snapshot")
def topic_snapshot(slug: str):
    return {
        "state": load_state(slug),
        "sessions": load_sessions(slug),
        "messages": read_messages(slug),
        "events": read_events(slug),
        "prompt_deliveries": list_prompt_deliveries(slug),
    }


@router.post("/round-stream")
def run_full_round_stream(
    slug: str,
    content: str = Form(...),
    agent_order: str = Form("codex,claudecode"),
):
    order = [item.strip() for item in agent_order.split(",") if item.strip()]
    gen = stream_full_round(slug, content.strip(), order)
    return StreamingResponse(_run_generator_in_background(gen, slug), media_type="application/x-ndjson")


@router.post("/cancel")
def cancel_round(slug: str):
    try:
        cancel_topic(slug)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True}

@router.post("/nudge-stream")
def nudge_agent_stream(slug: str, agent: str = Form(...)):
    try:
        gen = stream_nudge_agent(slug, agent.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(_run_generator_in_background(gen, slug), media_type="application/x-ndjson")


@router.post("/continue-stream")
def continue_round_stream(slug: str):
    gen = stream_continue_round(slug)
    return StreamingResponse(_run_generator_in_background(gen, slug), media_type="application/x-ndjson")


@router.post("/cancel")
def cancel_round(slug: str):
    try:
        cancel_topic(slug)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True}
