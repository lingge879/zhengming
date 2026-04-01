from __future__ import annotations

from .message_service import append_message as append_message_record
from .message_service import list_messages


def normalize_message_content(content: str) -> str:
    return content.strip()


def append_message(slug: str, speaker: str, content: str) -> dict:
    return append_message_record(slug, speaker, normalize_message_content(content))


def read_messages(slug: str) -> list[dict]:
    return list_messages(slug)

