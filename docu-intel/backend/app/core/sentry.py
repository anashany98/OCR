"""GlitchTip / Sentry SDK initialization for the backend.

GlitchTip exposes a Sentry-compatible API, so the official ``sentry-sdk`` package
works as-is. This module is a thin wrapper that:

* reads the DSN from settings (disabled when empty)
* sets sensible defaults for an internal tool (no PII, low sample rate)
* integrates with FastAPI so unhandled exceptions and request spans are captured
* exposes a no-op ``capture_exception`` for callers that want to report errors
  without depending on the SDK directly
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_initialized: bool = False


def init_sentry() -> None:
    """Initialise the Sentry SDK if a DSN is configured.

    Safe to call multiple times; subsequent calls are no-ops.
    """
    global _initialized
    if _initialized:
        return

    # Lazy import so test environments that don't need Sentry can skip the dep.
    from app.core.config import settings

    if not settings.sentry_dsn:
        logger.debug("sentry_disabled reason=no_dsn")
        _initialized = True
        return

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    environment = settings.sentry_environment or settings.environment
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=environment,
        release=f"docuintel-backend@{settings.app_name}",
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        send_default_pii=settings.sentry_send_pii,
        integrations=[
            FastApiIntegration(transaction_style="url"),
            StarletteIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
    )
    _initialized = True
    logger.info(
        "sentry_initialized environment=%s sample_rate=%.2f",
        environment,
        settings.sentry_traces_sample_rate,
    )


def capture_exception(error: BaseException, **extra: Any) -> None:
    """Capture an exception in GlitchTip if Sentry is enabled; no-op otherwise.

    ``extra`` is forwarded as a tag context. We don't use ``set_tag`` for
    arbitrary keys to avoid cardinality explosions; pass strings only.
    """
    if not _initialized:
        return
    try:
        import sentry_sdk

        with sentry_sdk.isolation_scope() as scope:
            for key, value in extra.items():
                scope.set_tag(str(key), str(value))
            sentry_sdk.capture_exception(error)
    except Exception as exc:  # pragma: no cover - never let tracking crash callers
        logger.warning("sentry_capture_failed error=%s", exc)


def capture_message(message: str, level: str = "info", **extra: Any) -> None:
    """Capture a non-exception event in GlitchTip if Sentry is enabled."""
    if not _initialized:
        return
    try:
        import sentry_sdk

        with sentry_sdk.isolation_scope() as scope:
            for key, value in extra.items():
                scope.set_tag(str(key), str(value))
            sentry_sdk.capture_message(message, level=level)
    except Exception as exc:  # pragma: no cover
        logger.warning("sentry_capture_message_failed error=%s", exc)
