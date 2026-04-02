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
from fastapi import HTTPException, File, UploadFile
import time as _time
import uuid as _uuid

@app.get("/artifacts/{slug}/{filename}")
def serve_artifact(slug: str, filename: str):
    for base in (WORKSPACES_DIR, LEGACY_TOPICS_DIR):
        path = base / slug / "artifacts" / filename
        if path.exists() and path.is_file():
            return FileResponse(path)
    raise HTTPException(status_code=404, detail="not found")

# Temp upload (no slug needed, for home page)
TEMP_UPLOADS = WORKSPACES_DIR.parent / "data" / "tmp_uploads"

@app.post("/api/upload-temp")
async def upload_temp(file: UploadFile = File(...)):
    TEMP_UPLOADS.mkdir(parents=True, exist_ok=True)
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "png"
    if ext not in ("png", "jpg", "jpeg", "gif", "webp", "svg"):
        ext = "png"
    name = f"{int(_time.time() * 1000)}-{_uuid.uuid4().hex[:6]}.{ext}"
    dest = TEMP_UPLOADS / name
    dest.write_bytes(await file.read())
    return {"ok": True, "markdown": f"![{file.filename or name}](/tmp-uploads/{name})"}

@app.get("/tmp-uploads/{filename}")
def serve_temp_upload(filename: str):
    path = TEMP_UPLOADS / filename
    if path.exists() and path.is_file():
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="not found")


app.include_router(pages.router)
app.include_router(api_topics.router)
app.include_router(api_turns.router)
