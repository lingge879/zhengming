from __future__ import annotations

import json

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse

from ..services.discussion_service import read_messages
from ..services.event_service import read_events
from ..services.orchestrator import (
    handle_user_message,
    run_current_agent,
    stream_continue_round,
    stream_current_agent,
    stream_full_round,
)
from ..services.session_service import load_sessions
from ..services.state_service import load_state


router = APIRouter(prefix="/api/topics/{slug}", tags=["turns"])


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
        "events": read_events(slug, limit=500),
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
            "events": read_events(slug, limit=500),
        }
        yield json.dumps(snapshot, ensure_ascii=False) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.get("/snapshot")
def topic_snapshot(slug: str):
    return {
        "state": load_state(slug),
        "sessions": load_sessions(slug),
        "messages": read_messages(slug),
        "events": read_events(slug, limit=500),
    }


@router.post("/round-stream")
def run_full_round_stream(
    slug: str,
    content: str = Form(...),
    agent_order: str = Form("codex,claudecode"),
):
    def event_stream():
        try:
            order = [item.strip() for item in agent_order.split(",") if item.strip()]
            for packet in stream_full_round(slug, content.strip(), order):
                yield json.dumps(packet, ensure_ascii=False) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"
        snapshot = {
            "type": "snapshot",
            "state": load_state(slug),
            "sessions": load_sessions(slug),
            "messages": read_messages(slug),
            "events": read_events(slug, limit=500),
        }
        yield json.dumps(snapshot, ensure_ascii=False) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/continue-stream")
def continue_round_stream(slug: str):
    def event_stream():
        try:
            for packet in stream_continue_round(slug):
                yield json.dumps(packet, ensure_ascii=False) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"
        snapshot = {
            "type": "snapshot",
            "state": load_state(slug),
            "sessions": load_sessions(slug),
            "messages": read_messages(slug),
            "events": read_events(slug, limit=500),
        }
        yield json.dumps(snapshot, ensure_ascii=False) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")
