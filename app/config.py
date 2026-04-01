from __future__ import annotations

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
TOPICS_DIR = BASE_DIR / "topics"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "app" / "static"
DEFAULT_DOCS_DIR = BASE_DIR / "defaults"

DEFAULT_SPEAKER_ORDER = ["user", "codex", "claudecode"]
DEFAULT_AGENT_LIST = ["codex", "claudecode"]
