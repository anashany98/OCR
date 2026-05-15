from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.api.routes.search import csv_safe_cell


def test_password_hash_roundtrip_and_token_subject():
    password_hash = hash_password("admin123")

    assert password_hash != "admin123"
    assert verify_password("admin123", password_hash)
    assert not verify_password("wrong", password_hash)

    token = create_access_token(subject="42")
    payload = decode_access_token(token)

    assert payload["sub"] == "42"


def test_csv_export_cells_escape_formula_prefixes():
    assert csv_safe_cell("=HYPERLINK(\"http://bad\")") == "'=HYPERLINK(\"http://bad\")"
    assert csv_safe_cell("+SUM(1,2)") == "'+SUM(1,2)"
    assert csv_safe_cell("-10") == "'-10"
    assert csv_safe_cell("@cmd") == "'@cmd"
    assert csv_safe_cell("texto normal") == "texto normal"
