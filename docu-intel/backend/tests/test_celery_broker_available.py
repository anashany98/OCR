"""S1.2 — ``_celery_broker_available`` contract.

Regression test for the M-12 follow-up. The previous implementation
bound the Celery ``connection_or_acquire`` context manager to
``conn`` and then used ``with conn:`` — which works only when Celery
returns a context manager that is *also* a connection. In practice
this was fragile across Celery versions and could make the helper
report the broker as unavailable even when Redis was reachable, which
caused ingestion to skip the ``embed_document_task`` enqueue.

The fix is to use the context manager form
(``with celery_app.connection_or_acquire() as conn:``) so the
connection is acquired *inside* the ``with`` block. This test
exercises both the test-mode fast path and the broker-reachability
path with a fake Celery app to make sure neither branch is
regressed.
"""
from __future__ import annotations

import importlib
import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def reload_module():
    """Reload ``document_processing_core`` with the env cleared so
    the function picks up a fresh module-level state between tests.
    """
    for var in ("CELERY_ALWAYS_EAGER", "TESTING"):
        os.environ.pop(var, None)
    import app.services.document_processing_core as module

    importlib.reload(module)
    yield module
    # Best-effort cleanup; do not fail the test if reload raises.
    for var in ("CELERY_ALWAYS_EAGER", "TESTING"):
        os.environ.pop(var, None)


def test_returns_false_when_testing_env_set(reload_module):
    """The fast-path branch must short-circuit when ``TESTING`` is set,
    so unit tests do not try to talk to a real broker.
    """
    os.environ["TESTING"] = "1"
    assert reload_module._celery_broker_available() is False


def test_returns_false_when_celery_always_eager_set(reload_module):
    """Same fast-path branch but for the Celery-native flag."""
    os.environ["CELERY_ALWAYS_EAGER"] = "1"
    assert reload_module._celery_broker_available() is False


def test_uses_context_manager_form(reload_module):
    """Regression guard for the original bug. The previous
    implementation captured the context manager into a name and
    then wrapped *that* in a ``with`` block. The fix is to use
    ``with celery_app.connection_or_acquire() as conn:`` so the
    connection is acquired *inside* the ``with`` block.

    We assert the structural form by introspecting the function
    source: the literal string
    ``with celery_app.connection_or_acquire() as conn`` must
    appear. A future refactor that re-introduces the buggy
    ``conn = celery_app.connection_or_acquire()`` form will fail
    this test.
    """
    from pathlib import Path

    source = Path("app/services/document_processing_core.py").read_text(encoding="utf-8")
    assert "with celery_app.connection_or_acquire() as conn" in source, (
        "document_processing_core._celery_broker_available must use "
        "the context manager form `with celery_app.connection_or_acquire() as conn`. "
        "The previous form (`conn = celery_app.connection_or_acquire(); with conn: ...`) "
        "silently broke the broker reachability check across Celery versions."
    )
    assert "conn = celery_app.connection_or_acquire()" not in source, (
        "document_processing_core._celery_broker_available must not "
        "bind the context manager to a name before entering the `with` block."
    )


def test_returns_true_when_broker_reachable(reload_module):
    """When the fake Celery app reports a healthy connection, the
    helper must return True. The ``ensure_connection`` call must
    happen on the *connection* (i.e. inside the ``with`` block), not
    on the context manager itself.
    """
    fake_connection = MagicMock()
    fake_app = MagicMock()
    # Make ``fake_app.connection_or_acquire()`` a context manager
    # whose ``__enter__`` returns the fake connection.
    cm = MagicMock()
    cm.__enter__.return_value = fake_connection
    cm.__exit__.return_value = False
    fake_app.connection_or_acquire.return_value = cm

    with patch.dict(os.environ, {}, clear=True), patch(
        "app.workers.celery_app.celery_app", fake_app, create=True
    ):
        assert reload_module._celery_broker_available() is True
    fake_connection.ensure_connection.assert_called_once()


def test_returns_false_when_broker_unreachable(reload_module):
    """If ``ensure_connection`` raises, the helper must swallow the
    exception and return False. The exception path is the one that
    was silently over-triggering in production.
    """
    fake_connection = MagicMock()
    fake_connection.ensure_connection.side_effect = ConnectionError("redis is down")
    cm = MagicMock()
    cm.__enter__.return_value = fake_connection
    cm.__exit__.return_value = False
    fake_app = MagicMock()
    fake_app.connection_or_acquire.return_value = cm

    with patch.dict(os.environ, {}, clear=True), patch(
        "app.workers.celery_app.celery_app", fake_app, create=True
    ):
        assert reload_module._celery_broker_available() is False
