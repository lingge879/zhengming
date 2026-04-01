from __future__ import annotations

import time

from fastapi import APIRouter, Body, Form, HTTPException
from fastapi.responses import RedirectResponse

from ..services.orchestrator import handle_user_message
from ..services.state_service import set_speaker_order
from ..services.topic_service import create_topic
from ..services.workspace_service import (
    default_agents_doc,
    default_claude_doc,
    ensure_workspace_initialized,
    read_text,
    slugify,
    workspace_files,
    write_text,
)


router = APIRouter(prefix="/api/topics", tags=["topics"])


def _build_session_slug(content: str) -> str:
    base = content.strip().splitlines()[0][:36]
    return slugify(f"{base}-{int(time.time() * 1000)}")


def _normalize_agent_order(raw: str) -> list[str]:
    requested = [item.strip() for item in raw.split(",") if item.strip()]
    normalized = [agent for agent in requested if agent in {"codex", "claudecode"}]
    deduped = list(dict.fromkeys(normalized))
    if not deduped:
        raise HTTPException(status_code=400, detail="至少选择一个 agent")
    return deduped


@router.post("")
def create_topic_action(
    title: str = Form(...),
    slug: str = Form(""),
    description: str = Form(""),
):
    final_slug = slugify(slug or title)
    try:
        create_topic(title=title.strip(), slug=final_slug, description=description.strip())
    except FileExistsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/topics/{final_slug}", status_code=303)


@router.post("/start-session")
def start_session_action(
    content: str = Form(...),
    agent_order: str = Form("codex,claudecode"),
):
    normalized = content.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="首条消息不能为空")

    title = normalized.splitlines()[0].strip()[:80] or "新会话"
    slug = _build_session_slug(normalized)
    selected_agents = _normalize_agent_order(agent_order)
    try:
        create_topic(title=title, slug=slug, description="")
        set_speaker_order(slug, selected_agents)
        handle_user_message(slug, normalized)
    except FileExistsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/topics/{slug}", status_code=303)


@router.get("/{slug}/workspace-docs")
def get_workspace_docs(slug: str):
    ensure_workspace_initialized(slug)
    files = workspace_files(slug)
    if not files["root"].exists():
        raise HTTPException(status_code=404, detail="topic 不存在")
    return {
        "agents": read_text(files["agents"]).strip() or default_agents_doc(files["root"]),
        "claude": read_text(files["claude"]).strip() or default_claude_doc(files["root"]),
    }


@router.post("/{slug}/workspace-docs")
def update_workspace_docs(
    slug: str,
    payload: dict = Body(...),
):
    ensure_workspace_initialized(slug)
    files = workspace_files(slug)
    if not files["root"].exists():
        raise HTTPException(status_code=404, detail="topic 不存在")
    agents_text = str(payload.get("agents", "")).strip() or default_agents_doc(files["root"])
    claude_text = str(payload.get("claude", "")).strip() or default_claude_doc(files["root"])
    write_text(files["agents"], agents_text)
    write_text(files["claude"], claude_text)
    return {"ok": True}
