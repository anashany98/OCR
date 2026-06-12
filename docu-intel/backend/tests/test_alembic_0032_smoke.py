"""Sanity check: the alembic migration module is importable and has the expected hooks."""
import importlib.util
from pathlib import Path

_migration_path = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0032_ocr_cascade_attempts.py"
)
spec = importlib.util.spec_from_file_location("mig_0032", _migration_path)
mig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mig)


def test_migration_metadata():
    assert mig.revision == "0032_ocr_cascade_attempts"
    assert mig.down_revision == "0031_pg_trgm_text_search_indexes"
    assert callable(mig.upgrade)
    assert callable(mig.downgrade)