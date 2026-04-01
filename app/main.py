from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import STATIC_DIR
from .db import init_db
from .routers import api_topics, api_turns, pages
from .services.topic_service import sync_all_topics


app = FastAPI(title="Agent Deliberation System")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    sync_all_topics()


app.include_router(pages.router)
app.include_router(api_topics.router)
app.include_router(api_turns.router)

