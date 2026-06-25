from __future__ import annotations

import logging
import time
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger("app.ingestion.stability")

IGNORED_SUFFIXES = {".tmp", ".part", ".crdownload", ".download", ".swp"}


# WATCH-1 (Sprint 2): maximum file size the watcher will try to
# enqueue. Matches the HTTP ``max_upload_size_mb`` so a file that
# would be rejected by the upload endpoint is also rejected by
# the watcher. A 1 GB file copied onto the volume must not be
# fed to the OCR pipeline; the worker would time out and the
# disk would fill up. The cap is read from the
# ``ingestion_max_file_size_mb`` setting (default 500 MB to
# match the HTTP cap). Set to 0 to disable (NOT recommended).
def get_max_file_size_bytes() -> int:
    mb = settings.ingestion_max_file_size_mb or 0
    if mb <= 0:
        return 0  # 0 = disabled
    return mb * 1024 * 1024


def is_ignored_path(path: Path) -> bool:
    return path.name.startswith(".") or path.suffix.lower() in IGNORED_SUFFIXES


def is_allowed_file_path(path: Path) -> bool:
    allowed = {suffix.lower() for suffix in settings.allowed_file_extensions}
    return not allowed or path.suffix.lower() in allowed


def is_file_too_large(path: Path) -> bool:
    """Return True if ``path`` exceeds the watcher size cap.

    WATCH-1 (Sprint 2): a 600 MB file copied onto the volume
    must NOT be fed to the OCR pipeline. The previous
    implementation had no cap, so a runaway upload could
    hang the worker for hours and exhaust the disk.
    """
    cap = get_max_file_size_bytes()
    if cap <= 0:
        return False  # cap disabled
    try:
        size = path.stat().st_size
    except OSError:
        return False  # unreadable file is not "too large", it's broken
    return size > cap


def is_file_stable(
    path: Path,
    stable_seconds: float,
    *,
    now: float | None = None,
    double_check_delay: float = 2.0,
) -> bool:
    """Return True if ``path`` is a regular file whose size and
    mtime have not changed across two ``stat()`` calls separated
    by ``double_check_delay`` seconds.

    WATCH-1 (Sprint 2): the previous implementation only did
    ONE ``stat()`` and accepted the file if its mtime was
    older than ``stable_seconds``. If a large file is still
    being copied at the moment of the check, its mtime is
    still being updated, but the single-stat heuristic would
    already pass because the most recent mtime is ``now``. To
    detect "still being written" we now do a quick two-stat
    comparison: if size OR mtime changed between the two
    calls, the file is not stable.

    The delay defaults to 2.0 s, which is short enough not to
    add noticeable latency to the watcher tick but long enough
    to catch a file that is being copied at line-speed over
    the network.
    """
    if stable_seconds <= 0:
        return path.is_file()
    try:
        stat1 = path.stat()
    except FileNotFoundError:
        return False
    if not path.is_file():
        return False
    current_time = time.time() if now is None else now
    if current_time - stat1.st_mtime < stable_seconds:
        return False
    # The mtime is already older than the threshold; do a
    # second check after ``double_check_delay`` to ensure the
    # file is not still being written.
    if double_check_delay > 0:
        # We sleep using the caller's ``now`` if provided so
        # tests can run the function without a real sleep. In
        # production, ``now`` is None and we use ``time.time``.
        if now is None:
            time.sleep(double_check_delay)
        try:
            stat2 = path.stat()
        except FileNotFoundError:
            return False
        if stat2.st_size != stat1.st_size or stat2.st_mtime != stat1.st_mtime:
            # File is still being written.
            logger.debug(
                "file_not_stable size_or_mtime_changed path=%s",
                path,
            )
            return False
    return True
