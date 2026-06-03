"""Tests for GlitchTip / Sentry error tracking integration."""
from __future__ import annotations

from unittest.mock import patch

from app.core.sentry import capture_exception, capture_message, init_sentry


def test_init_sentry_is_noop_when_dsn_empty(monkeypatch):
    """When SENTRY_DSN is empty, init must not call sentry_sdk.init and must not crash."""
    from app.core import sentry as sentry_module

    monkeypatch.setattr(sentry_module, "_initialized", False)
    monkeypatch.setattr("app.core.config.settings.sentry_dsn", "")

    with patch("sentry_sdk.init") as mock_init:
        init_sentry()
        mock_init.assert_not_called()
    assert sentry_module._initialized is True


def test_init_sentry_calls_sdk_with_settings(monkeypatch):
    """When SENTRY_DSN is set, sentry_sdk.init is called with the expected kwargs."""
    from app.core import sentry as sentry_module

    monkeypatch.setattr(sentry_module, "_initialized", False)
    monkeypatch.setattr("app.core.config.settings.sentry_dsn", "https://k@glitchtip/1")
    monkeypatch.setattr("app.core.config.settings.sentry_traces_sample_rate", 0.1)
    monkeypatch.setattr("app.core.config.settings.sentry_profiles_sample_rate", 0.0)
    monkeypatch.setattr("app.core.config.settings.sentry_environment", "")
    monkeypatch.setattr("app.core.config.settings.environment", "staging")
    monkeypatch.setattr("app.core.config.settings.sentry_send_pii", False)

    with patch("sentry_sdk.init") as mock_init:
        init_sentry()
        assert mock_init.called
        kwargs = mock_init.call_args.kwargs
        assert kwargs["dsn"] == "https://k@glitchtip/1"
        assert kwargs["environment"] == "staging"
        assert kwargs["traces_sample_rate"] == 0.1
        assert kwargs["send_default_pii"] is False
        # FastAPI + Starlette + Logging integrations
        integration_names = [type(i).__name__ for i in kwargs["integrations"]]
        assert "FastApiIntegration" in integration_names
        assert "StarletteIntegration" in integration_names
        assert "LoggingIntegration" in integration_names


def test_init_sentry_is_idempotent(monkeypatch):
    """Multiple init calls must not re-init the SDK."""
    from app.core import sentry as sentry_module

    monkeypatch.setattr(sentry_module, "_initialized", False)
    monkeypatch.setattr("app.core.config.settings.sentry_dsn", "")

    with patch("sentry_sdk.init") as mock_init:
        init_sentry()
        init_sentry()
        init_sentry()
        mock_init.assert_not_called()


def test_capture_exception_is_noop_when_not_initialized(monkeypatch):
    """capture_exception must short-circuit when init_sentry was never called."""
    from app.core import sentry as sentry_module

    monkeypatch.setattr(sentry_module, "_initialized", False)

    with patch("sentry_sdk.capture_exception") as mock_capture:
        capture_exception(RuntimeError("boom"), document_id=42)
        mock_capture.assert_not_called()


def test_capture_message_is_noop_when_not_initialized(monkeypatch):
    """capture_message must short-circuit when init_sentry was never called."""
    from app.core import sentry as sentry_module

    monkeypatch.setattr(sentry_module, "_initialized", False)

    with patch("sentry_sdk.capture_message") as mock_capture:
        capture_message("hello", level="warning", scope="test")
        mock_capture.assert_not_called()


def test_capture_exception_does_not_propagate_sentry_errors(monkeypatch):
    """If Sentry is broken, capture_exception must not raise to the caller."""
    from app.core import sentry as sentry_module

    # Simulate "initialized" but with a broken SDK import
    monkeypatch.setattr(sentry_module, "_initialized", True)

    def _raise(*args, **kwargs):
        raise RuntimeError("Sentry SDK exploded")

    with patch("sentry_sdk.capture_exception", side_effect=_raise):
        # Must not raise
        capture_exception(RuntimeError("original"))


def test_capture_exception_forwards_tags(monkeypatch):
    """When Sentry is enabled, extra kwargs become tags on the captured event."""
    from app.core import sentry as sentry_module

    monkeypatch.setattr(sentry_module, "_initialized", True)

    captured_tags: dict[str, str] = {}

    class _FakeScope:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def set_tag(self, key, value):
            captured_tags[key] = value

    with patch("sentry_sdk.isolation_scope", return_value=_FakeScope()), patch(
        "sentry_sdk.capture_exception"
    ) as mock_capture:
        capture_exception(ValueError("x"), document_id=7, budget_code="245745")
        assert captured_tags == {"document_id": "7", "budget_code": "245745"}
        assert mock_capture.called
