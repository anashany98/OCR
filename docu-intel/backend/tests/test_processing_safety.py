from app.parsers.router import IMAGE_EXTENSIONS
from app.services.document_service import sanitize_text_for_database


def test_webp_is_processed_as_image_not_plain_text():
    assert ".webp" in IMAGE_EXTENSIONS


def test_sanitizes_nul_bytes_before_postgres_text_insert():
    assert sanitize_text_for_database("abc\x00def") == "abcdef"

