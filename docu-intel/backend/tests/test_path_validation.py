"""F0-06: Tests for normalize_untrusted_relative_path."""
import pytest
from app.services.document_registration_service import normalize_untrusted_relative_path


class TestNormalizeUntrustedRelativePath:
    """Path traversal and injection prevention tests."""

    # --- Valid paths ---------------------------------------------------
    def test_simple_relative_path(self):
        assert normalize_untrusted_relative_path("docs/file.pdf") == "docs/file.pdf"

    def test_nested_path(self):
        assert normalize_untrusted_relative_path("a/b/c/file.pdf") == "a/b/c/file.pdf"

    def test_single_filename(self):
        assert normalize_untrusted_relative_path("file.pdf") == "file.pdf"

    def test_with_user_id_prefix(self):
        result = normalize_untrusted_relative_path("docs/file.pdf", user_id=42)
        assert result == "upload/42/docs/file.pdf"

    def test_dots_in_filename_are_kept(self):
        assert normalize_untrusted_relative_path("my.file.v2.pdf") == "my.file.v2.pdf"

    def test_path_with_spaces(self):
        assert normalize_untrusted_relative_path("my docs/file.pdf") == "my docs/file.pdf"

    # --- Absolute paths ------------------------------------------------
    def test_unix_absolute_rejected(self):
        with pytest.raises(ValueError, match="absolute"):
            normalize_untrusted_relative_path("/etc/passwd")

    def test_windows_drive_rejected(self):
        with pytest.raises(ValueError, match="Windows"):
            normalize_untrusted_relative_path("C:\\Windows\\system32\\config")

    def test_unc_path_rejected(self):
        with pytest.raises(ValueError, match="UNC"):
            normalize_untrusted_relative_path("\\\\server\\share\\file")

    # --- Directory traversal -------------------------------------------
    def test_single_dotdot_rejected(self):
        with pytest.raises(ValueError, match="\\.\\."):
            normalize_untrusted_relative_path("../etc/passwd")

    def test_embedded_dotdot_rejected(self):
        with pytest.raises(ValueError, match="\\.\\."):
            normalize_untrusted_relative_path("docs/../../etc/passwd")

    def test_dotdot_at_end_rejected(self):
        with pytest.raises(ValueError, match="\\.\\."):
            normalize_untrusted_relative_path("docs/..")

    # --- Backslash normalization ---------------------------------------
    def test_backslash_normalized_to_slash(self):
        assert normalize_untrusted_relative_path("docs\\file.pdf") == "docs/file.pdf"

    def test_mixed_slashes_normalized(self):
        assert normalize_untrusted_relative_path("docs/sub\\file.pdf") == "docs/sub/file.pdf"

    def test_backslash_traversal_rejected(self):
        with pytest.raises(ValueError, match="\\.\\."):
            normalize_untrusted_relative_path("docs\\..\\etc\\passwd")

    # --- Edge cases ----------------------------------------------------
    def test_empty_string_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            normalize_untrusted_relative_path("")

    def test_whitespace_only_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            normalize_untrusted_relative_path("   ")

    def test_null_byte_rejected(self):
        with pytest.raises(ValueError, match="null"):
            normalize_untrusted_relative_path("docs/file\x00.pdf")

    def test_dot_only_resolves_to_empty(self):
        with pytest.raises(ValueError, match="empty"):
            normalize_untrusted_relative_path(".")

    def test_double_slash_collapsed(self):
        assert normalize_untrusted_relative_path("docs//file.pdf") == "docs/file.pdf"

    # --- Namespace isolation -------------------------------------------
    def test_user_id_42(self):
        result = normalize_untrusted_relative_path("file.pdf", user_id=42)
        assert result == "upload/42/file.pdf"

    def test_user_id_none_no_prefix(self):
        result = normalize_untrusted_relative_path("file.pdf", user_id=None)
        assert result == "file.pdf"
