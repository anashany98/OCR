"""
Unit tests for WATCH-1 (Sprint 2).

Verifies:

1. ``is_file_too_large`` rejects files over the cap.
2. ``is_file_stable`` now does a double-check (size + mtime
   unchanged after a short delay) to catch files still being
   written.
3. ``enqueue_existing_files`` stops at the configured limit
   and skips oversized files.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "x" * 64)
os.environ.setdefault("ADMIN_PASSWORD", "y" * 22)


# ---------------------------------------------------------------------------
# is_file_too_large
# ---------------------------------------------------------------------------


class TestIsFileTooLarge:
    def test_small_file_not_too_large(self, tmp_path):
        from app.ingestion.stability import is_file_too_large

        f = tmp_path / "small.pdf"
        f.write_bytes(b"x" * 1000)
        assert is_file_too_large(f) is False

    def test_large_file_rejected(self, tmp_path, monkeypatch):
        from app.ingestion.stability import is_file_too_large

        f = tmp_path / "huge.pdf"
        # Write a 1-byte file but mock stat to report 600 MB.
        f.write_bytes(b"x")
        monkeypatch.setattr(
            "app.ingestion.stability.get_max_file_size_bytes",
            lambda: 500 * 1024 * 1024,  # 500 MB cap
        )
        # Mock stat to report a large file.
        import os as _os

        original_stat = _os.stat

        class FakeStat:
            st_size = 600 * 1024 * 1024
            st_mtime = time.time()

        def fake_stat(path, *args, **kwargs):
            if str(path) == str(f):
                return FakeStat()
            return original_stat(path, *args, **kwargs)

        monkeypatch.setattr(_os, "stat", fake_stat)
        assert is_file_too_large(f) is True

    def test_cap_disabled_returns_false(self, tmp_path, monkeypatch):
        """When cap is 0 (disabled), no file is too large."""
        from app.ingestion.stability import is_file_too_large

        f = tmp_path / "any.pdf"
        f.write_bytes(b"x")
        monkeypatch.setattr(
            "app.ingestion.stability.get_max_file_size_bytes",
            lambda: 0,
        )
        assert is_file_too_large(f) is False


# ---------------------------------------------------------------------------
# is_file_stable double-check
# ---------------------------------------------------------------------------


class TestIsFileStableDoubleCheck:
    def test_stable_file_passes(self, tmp_path):
        from app.ingestion.stability import is_file_stable

        f = tmp_path / "stable.pdf"
        f.write_bytes(b"content")
        # Old mtime (> 30s ago)
        old_time = time.time() - 60
        os.utime(f, (old_time, old_time))
        # No double-check when double_check_delay=0
        assert is_file_stable(f, 30, now=time.time(), double_check_delay=0) is True

    def test_unstable_recent_file_fails(self, tmp_path):
        from app.ingestion.stability import is_file_stable

        f = tmp_path / "recent.pdf"
        f.write_bytes(b"content")
        # Recent mtime (< 30s ago)
        assert is_file_stable(f, 30, now=time.time(), double_check_delay=0) is False

    def test_double_check_detects_size_change(self, tmp_path, monkeypatch):
        """If the file size changes between the two stat() calls,
        the file is not stable.
        """
        from app.ingestion.stability import is_file_stable

        f = tmp_path / "writing.pdf"
        f.write_bytes(b"small")
        old_time = time.time() - 60
        os.utime(f, (old_time, old_time))

        # Mock time.sleep to be instant
        monkeypatch.setattr(time, "sleep", lambda _: None)

        # Simulate size change: first stat reports 5 bytes, second
        # reports 10 bytes.
        import os as _os
        import stat as _stat

        original_stat = _os.stat
        call_count = {"n": 0}

        class Stat5:
            st_size = 5
            st_mtime = old_time
            st_mode = _stat.S_IFREG

        class Stat10:
            st_size = 10
            st_mtime = old_time
            st_mode = _stat.S_IFREG

        def fake_stat(path, *args, **kwargs):
            if str(path) == str(f):
                call_count["n"] += 1
                return Stat5() if call_count["n"] == 1 else Stat10()
            return original_stat(path, *args, **kwargs)

        monkeypatch.setattr(_os, "stat", fake_stat)
        result = is_file_stable(f, 30, now=time.time(), double_check_delay=0.01)
        assert result is False

    def test_nonexistent_file_returns_false(self, tmp_path):
        from app.ingestion.stability import is_file_stable

        f = tmp_path / "missing.pdf"
        assert is_file_stable(f, 30, now=time.time()) is False


# ---------------------------------------------------------------------------
# enqueue_existing_files
# ---------------------------------------------------------------------------


class TestEnqueueExistingFiles:
    def test_respects_limit(self, tmp_path, monkeypatch):
        from app.ingestion.stability import is_file_too_large
        from app.ingestion.watcher import enqueue_existing_files, PendingFileRegistry

        monkeypatch.setattr(
            "app.ingestion.watcher.is_file_too_large",
            lambda _: False,
        )
        monkeypatch.setattr(
            "app.ingestion.watcher.is_ignored_path",
            lambda _: False,
        )
        monkeypatch.setattr(
            "app.ingestion.watcher.is_allowed_file_path",
            lambda _: True,
        )
        # Create 20 files.
        for i in range(20):
            (tmp_path / f"f{i:02d}.pdf").write_bytes(b"x")
        pending = PendingFileRegistry()
        count = enqueue_existing_files(pending, tmp_path, limit=5)
        assert count == 5

    def test_skips_oversized_files(self, tmp_path, monkeypatch):
        from app.ingestion.watcher import enqueue_existing_files, PendingFileRegistry

        # Mark every file as "too large".
        monkeypatch.setattr(
            "app.ingestion.watcher.is_file_too_large",
            lambda _: True,
        )
        monkeypatch.setattr(
            "app.ingestion.watcher.is_ignored_path",
            lambda _: False,
        )
        monkeypatch.setattr(
            "app.ingestion.watcher.is_allowed_file_path",
            lambda _: True,
        )
        (tmp_path / "huge.pdf").write_bytes(b"x")
        pending = PendingFileRegistry()
        count = enqueue_existing_files(pending, tmp_path, limit=100)
        assert count == 0
        # The file was NOT added to pending.
        assert len(pending) == 0