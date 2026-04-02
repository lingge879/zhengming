from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse

from ..services.orchestrator import handle_user_message
from ..services.state_service import set_speaker_order
from ..services.topic_service import create_topic, delete_topic
from ..services.workspace_service import (
    default_agents_doc,
    default_claude_doc,
    ensure_workspace_initialized,
    read_text,
    workspace_files,
    write_text,
)


router = APIRouter(prefix="/api/topics", tags=["topics"])


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
    description: str = Form(""),
):
    try:
        _, actual_slug = create_topic(title=title.strip(), description=description.strip())
    except FileExistsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/topics/{actual_slug}", status_code=303)


@router.post("/start-session")
def start_session_action(
    content: str = Form(...),
    agent_order: str = Form("codex,claudecode"),
):
    normalized = content.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="首条消息不能为空")

    title = normalized.splitlines()[0].strip()[:80] or "新会话"
    selected_agents = _normalize_agent_order(agent_order)
    try:
        _, actual_slug = create_topic(title=title, description="")
        set_speaker_order(actual_slug, selected_agents)
        handle_user_message(actual_slug, normalized)
    except FileExistsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/topics/{actual_slug}", status_code=303)


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


@router.delete("/{slug}")
def delete_topic_action(slug: str):
    try:
        delete_topic(slug)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/{slug}/upload-image")
async def upload_image(slug: str, file: UploadFile = File(...)):
    ensure_workspace_initialized(slug)
    files = workspace_files(slug)
    if not files["root"].exists():
        raise HTTPException(status_code=404, detail="topic 不存在")

    artifacts = files["artifacts"]
    artifacts.mkdir(parents=True, exist_ok=True)

    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "png"
    if ext not in ("png", "jpg", "jpeg", "gif", "webp", "svg"):
        ext = "png"
    name = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}.{ext}"
    dest = artifacts / name

    content = await file.read()
    dest.write_bytes(content)

    return {
        "ok": True,
        "filename": name,
        "path": str(dest),
        "markdown": f"![{file.filename or name}](/artifacts/{slug}/{name})",
    }
