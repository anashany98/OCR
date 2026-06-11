"""
Unit tests for app.ingestion.stability
Tests file path filtering and stability detection logic.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Set DATABASE_URL before any app imports to prevent pydantic validation errors
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

# Patch settings module first to avoid pydantic_settings import error
import app.core.config
mock_settings = MagicMock()
mock_settings.allowed_file_extensions = [
    ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
    ".txt", ".csv", ".tsv", ".log", ".eml", ".xls", ".xlsx", ".xlsm"
]
app.core.config.settings = mock_settings

# Now we can import the stability module
from app.ingestion.stability import (
    IGNORED_SUFFIXES,
    is_ignored_path,
    is_allowed_file_path,
    is_file_stable,
)


class TestIsIgnoredPath:
    """Tests for is_ignored_path() function."""

    def test_returns_true_for_dotfile(self):
        assert is_ignored_path(Path("/data/.DS_Store")) is True
        assert is_ignored_path(Path("/data/.hidden.pdf")) is True

    def test_returns_true_for_ignored_suffixes(self):
        for suffix in IGNORED_SUFFIXES:
            assert is_ignored_path(Path(f"/data/file{suffix}")) is True, f"Failed for {suffix}"

    def test_returns_false_for_normal_files(self):
        assert is_ignored_path(Path("/data/document.pdf")) is False
        assert is_ignored_path(Path("/data/image.png")) is False
        assert is_ignored_path(Path("/data/data.csv")) is False

    def test_returns_false_for_clean_extensions(self):
        assert is_ignored_path(Path("/data/file.txt")) is False
        assert is_ignored_path(Path("/data/file.xlsx")) is False

    def test_extension_case_insensitive(self):
        assert is_ignored_path(Path("/data/file.TMP")) is True
        assert is_ignored_path(Path("/data/file.Part")) is True


class TestIsAllowedFilePath:
    """Tests for is_allowed_file_path() function."""

    def test_allows_known_extensions(self):
        assert is_allowed_file_path(Path("/data/file.pdf")) is True
        assert is_allowed_file_path(Path("/data/file.png")) is True
        assert is_allowed_file_path(Path("/data/photo.jpg")) is True
        assert is_allowed_file_path(Path("/data/file.txt")) is True

    def test_rejects_unknown_extensions(self):
        # .doc is not in allowed list, .xyz is not either
        assert is_allowed_file_path(Path("/data/file.doc")) is False
        assert is_allowed_file_path(Path("/data/file.xyz")) is False

    def test_extension_case_insensitive(self):
        assert is_allowed_file_path(Path("/data/file.PDF")) is True
        assert is_allowed_file_path(Path("/data/file.Pdf")) is True


class TestIsFileStable:
    """Tests for is_file_stable() function."""

    def test_zero_stable_seconds_checks_file_exists(self, tmp_path):
        file_path = tmp_path / "test.txt"
        file_path.write_text("content")
        assert is_file_stable(file_path, stable_seconds=0) is True

    def test_returns_false_for_nonexistent_file(self, tmp_path):
        assert is_file_stable(tmp_path / "nonexistent.pdf", stable_seconds=5) is False

    def test_stable_seconds_zero_means_immediately_stable(self, tmp_path):
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")
        assert is_file_stable(file_path, stable_seconds=0) is True

    def test_stable_seconds_negative_treated_as_zero(self, tmp_path):
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")
        # Negative stable_seconds treated as 0 - immediately stable
        assert is_file_stable(file_path, stable_seconds=-10) is True


class TestIgnoredSuffixesConstant:
    """Tests for IGNORED_SUFFIXES constant."""

    def test_contains_expected_values(self):
        expected = {".tmp", ".part", ".crdownload", ".download", ".swp"}
        assert IGNORED_SUFFIXES == expected