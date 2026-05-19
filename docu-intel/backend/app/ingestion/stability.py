from __future__ import annotations

import time
from pathlib import Path

from app.core.config import settings

IGNORED_SUFFIXES = {".tmp", ".part", ".crdownload", ".download", ".swp"}


def is_ignored_path(path: Path) -> bool:
    return path.name.startswith(".") or path.suffix.lower() in IGNORED_SUFFIXES


def is_allowed_file_path(path: Path) -> bool:
    allowed = {suffix.lower() for suffix in settings.allowed_file_extensions}
    return not allowed or path.suffix.lower() in allowed


def is_file_stable(path: Path, stable_seconds: float, *, now: float | None = None) -> bool:
    if stable_seconds <= 0:
        return path.is_file()
    try:
        stat = path.stat()
    except FileNotFoundError:
        return False
    current_time = time.time() if now is None else now
    return path.is_file() and current_time - stat.st_mtime >= stable_seconds
