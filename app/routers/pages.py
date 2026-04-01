from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..config import TEMPLATES_DIR
from ..services.discussion_service import read_messages
from ..services.event_service import read_events
from ..services.topic_service import get_topic, list_topics


router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "topics": list_topics(),
        },
    )


@router.get("/topics/{slug}", response_class=HTMLResponse)
def topic_detail(request: Request, slug: str):
    topic = get_topic(slug)
    messages = read_messages(slug)
    events = read_events(slug)
    return templates.TemplateResponse(
        request,
        "topic_detail.html",
        {
            "topic": topic,
            "messages": messages,
            "events": events,
            "topic_slug": slug,
        },
    )
