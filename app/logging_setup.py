from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import DATA_DIR, LOG_PATH


def setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger("agent_deliberation")
    if any(isinstance(handler, RotatingFileHandler) and getattr(handler, "baseFilename", "") == str(LOG_PATH) for handler in root_logger.handlers):
        return

    root_logger.setLevel(logging.INFO)
    root_logger.propagate = False

    file_handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
