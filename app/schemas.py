from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TopicCreateForm(BaseModel):
    title: str
    slug: str
    description: str = ""


class UserMessageForm(BaseModel):
    content: str = Field(min_length=1)


class TopicSummary(BaseModel):
    slug: str
    title: str
    status: str
    current_speaker: str
    updated_at: str


class AgentRunResult(BaseModel):
    agent: str
    run_id: str
    session_id: str | None
    message: str
    event_count: int
    raw: dict[str, Any] = Field(default_factory=dict)

