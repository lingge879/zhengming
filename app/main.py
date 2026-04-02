from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import STATIC_DIR, WORKSPACES_DIR, LEGACY_TOPICS_DIR
from .db import init_db
from .logging_setup import setup_logging
from .routers import api_topics, api_turns, pages
from .services.topic_service import sync_all_topics


app = FastAPI(title="Agent Deliberation System")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
def on_startup() -> None:
    setup_logging()
    init_db()
    sync_all_topics()


# Serve workspace artifacts (images etc.) at /artifacts/{slug}/{filename}
from fastapi.responses import FileResponse
from fastapi import HTTPException

@app.get("/artifacts/{slug}/{filename}")
def serve_artifact(slug: str, filename: str):
    for base in (WORKSPACES_DIR, LEGACY_TOPICS_DIR):
        path = base / slug / "artifacts" / filename
        if path.exists() and path.is_file():
            return FileResponse(path)
    raise HTTPException(status_code=404, detail="not found")


app.include_router(pages.router)
app.include_router(api_topics.router)
app.include_router(api_turns.router)
