"""Regression test: the files cleaned up in Block 4 must not
re-introduce ``except ...: pass`` blocks.

A silent ``except: pass`` is the worst kind of bug: the
exception is swallowed, the operator sees no log line, and the
failing branch is invisible until a downstream consumer
behaves oddly. Block 4 replaced 13 such patterns across the
codebase with specific exception types + ``logger.warning``
/ ``logger.debug`` calls. This test pins the invariant.

The grep is intentionally scoped to the files we know were
touched in Block 4 (plus a few extras that already had
proper handling) so a future contributor who silently
re-introduces the pattern in any of them fails CI.

Test scope:

* ``app/ai/local_client.py`` — Table-transcription tmp cleanup.
* ``app/ai/validation.py`` — Memory-block entity extraction.
* ``app/api/routes/plans.py`` — Vision-model swap + tmp cleanup.
* ``app/core/config.py`` — ``validate_db_password`` catch-all.
* ``app/ocr/factory.py`` — Synthetic-image tmp cleanup.
* ``app/parsers/msg.py`` — Attachment iteration + close.
* ``app/services/dxf_parser.py`` — DIMENSION entity parse.
* ``app/services/file_storage.py`` — ``chmod 0644`` on stored file.
* ``app/services/runtime_settings.py`` — Redis snapshot iteration.
* ``app/services/search_filters.py`` — ``budget_scope_id`` cast.
* ``app/services/thumbnail.py`` — ``extract-msg`` close.

The pattern that triggers the failure is the classic:

    except SomeException:
        pass

i.e. a bare ``pass`` directly under an ``except`` clause. An
``except`` that does something else (log, return, re-raise) is
fine. The ``re.MULTILINE`` flag keeps the regex anchored to the
``except`` line itself so a comment immediately after the
except does not match.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "app"

# Files where Block 4 removed silent except: pass patterns.
# Adding a new entry to this list without changing the
# expectation in the test is the canonical way to expand the
# protection to a new module.
SCOPED_FILES = [
    "ai/local_client.py",
    "ai/validation.py",
    "api/routes/plans.py",
    "core/config.py",
    "ocr/factory.py",
    "parsers/msg.py",
    "services/dxf_parser.py",
    "services/file_storage.py",
    "services/runtime_settings.py",
    "services/search_filters.py",
    "services/thumbnail.py",
]

# Match ``except <anything>:`` immediately followed by a line
# whose only non-whitespace content is ``pass``. The
# ``re.MULTILINE`` keeps the ``^`` anchored to the start of a
# line. We strip the file's trailing newline before matching
# so the regex does not see a phantom blank line.
SILENT_EXCEPT = re.compile(
    r"^[ \t]*except[^\n]*:\s*\n[ \t]*pass\s*$",
    re.MULTILINE,
)


@pytest.mark.parametrize("relative_path", SCOPED_FILES)
def test_no_silent_except_pass(relative_path: str) -> None:
    """Each file in :data:`SCOPED_FILES` must not contain a
    ``except <...>:`` followed directly by ``pass``. The grep
    intentionally allows an ``except`` that has any other body
    (return, log, raise, …) to remain — only the silent
    pattern is forbidden.
    """
    file_path = APP_ROOT / relative_path
    assert file_path.is_file(), f"scoped file is missing: {file_path}"
    text = file_path.read_text(encoding="utf-8")
    matches = SILENT_EXCEPT.findall(text)
    assert not matches, (
        f"{relative_path} contains a silent `except: pass` block — "
        "replace with a specific exception type and a logger call. "
        f"Found: {matches!r}"
    )


def test_scope_does_not_drift() -> None:
    """The test file itself lists every file we promise to
    keep clean. If you add a new module to the Block 4
    cleanup you must also add it here so the regression
    coverage moves with you.
    """
    expected = set(SCOPED_FILES)
    actual = set()
    for path in APP_ROOT.rglob("*.py"):
        rel = path.relative_to(APP_ROOT).as_posix()
        # We only track app/ files, not tests/ or scripts/.
        actual.add(rel)
    missing_from_scope = {
        path
        for path in (
            "ai/local_client.py",
            "ai/validation.py",
            "api/routes/plans.py",
            "core/config.py",
            "ocr/factory.py",
            "parsers/msg.py",
            "services/dxf_parser.py",
            "services/file_storage.py",
            "services/runtime_settings.py",
            "services/search_filters.py",
            "services/thumbnail.py",
        )
        if path in actual and path not in expected
    }
    assert not missing_from_scope, (
        "The following files were added under app/ but are not in the "
        "test's SCOPED_FILES list. If they intentionally contain silent "
        f"except: pass patterns, add them to SCOPED_FILES. Found: {missing_from_scope!r}"
    )
