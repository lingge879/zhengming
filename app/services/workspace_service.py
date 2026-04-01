from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import DEFAULT_DOCS_DIR, LEGACY_TOPICS_DIR, WORKSPACES_DIR
from ..db import get_conn


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+", "-", value.strip()).strip("-_").lower()
    if not slug:
        raise ValueError("slug 不能为空")
    return slug


def _workspace_path_from_db(slug: str) -> Path | None:
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT workspace_path FROM topics WHERE slug = ?",
                (slug,),
            ).fetchone()
    except Exception:
        return None
    if row is None or not row["workspace_path"]:
        return None
    return Path(row["workspace_path"])


def topic_path(slug: str) -> Path:
    db_path = _workspace_path_from_db(slug)
    if db_path is not None:
        return db_path
    workspace_path = WORKSPACES_DIR / slug
    if workspace_path.exists():
        return workspace_path
    return LEGACY_TOPICS_DIR / slug


def ensure_topics_dir() -> None:
    WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
    LEGACY_TOPICS_DIR.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def append_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(content)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_default_doc_template(filename: str, root: Path) -> str:
    path = DEFAULT_DOCS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"默认模板不存在: {path}")
    template = path.read_text(encoding="utf-8")
    return template.replace("{{WORKSPACE_ROOT}}", str(root))


def default_agents_doc(root: Path) -> str:
    return _load_default_doc_template("AGENTS.md", root)


def default_claude_doc(root: Path) -> str:
    return _load_default_doc_template("CLAUDE.md", root)


def migrate_workspace_docs(slug: str) -> None:
    return None


def workspace_files(slug: str) -> dict[str, Path]:
    root = topic_path(slug)
    return {
        "root": root,
        "agents": root / "AGENTS.md",
        "claude": root / "CLAUDE.md",
        "artifacts": root / "artifacts",
    }


def legacy_workspace_files(slug: str) -> dict[str, Path]:
    root = topic_path(slug)
    return {
        "codex": root / "CODEX.md",
        "state": root / "state.json",
        "sessions": root / "sessions.json",
        "config": root / "config.json",
    }


def remove_legacy_workspace_files(slug: str) -> None:
    for path in legacy_workspace_files(slug).values():
        path.unlink(missing_ok=True)


def ensure_workspace_initialized(slug: str) -> Path:
    files = workspace_files(slug)
    root = files["root"]
    if not root.exists():
        raise FileNotFoundError(slug)

    files["artifacts"].mkdir(parents=True, exist_ok=True)

    if not files["agents"].exists():
        write_text(files["agents"], default_agents_doc(root))
    elif not read_text(files["agents"]).strip():
        write_text(files["agents"], default_agents_doc(root))

    if not files["claude"].exists():
        write_text(files["claude"], default_claude_doc(root))
    elif not read_text(files["claude"]).strip():
        write_text(files["claude"], default_claude_doc(root))

    (root / "README.md").unlink(missing_ok=True)
    (root / "events.jsonl").unlink(missing_ok=True)
    migrate_workspace_docs(slug)
    return root


def _build_workspace_root() -> Path:
    ensure_topics_dir()
    base = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    candidate = WORKSPACES_DIR / base
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = WORKSPACES_DIR / f"{base}-{suffix:02d}"
    return candidate


def create_topic_workspace(title: str, slug: str, description: str) -> Path:
    ensure_topics_dir()
    legacy_root = LEGACY_TOPICS_DIR / slug
    if legacy_root.exists():
        raise FileExistsError(f"topic 已存在: {slug}")
    workspace_root = WORKSPACES_DIR / slug
    if workspace_root.exists():
        raise FileExistsError(f"workspace 已存在: {slug}")
    root = _build_workspace_root()
    files = {
        "root": root,
        "agents": root / "AGENTS.md",
        "claude": root / "CLAUDE.md",
        "artifacts": root / "artifacts",
    }

    files["artifacts"].mkdir(parents=True, exist_ok=True)

    agent_md = default_agents_doc(root)
    claude_md = default_claude_doc(root)

    write_text(files["agents"], agent_md)
    write_text(files["claude"], claude_md)

    return root
