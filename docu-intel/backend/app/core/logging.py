from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import structlog

from app.core.config import settings


def _utc_timestamp(*, utc: bool = True) -> str:
    """Return ISO 8601 UTC timestamp with millisecond precision."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def setup_logging() -> None:
    """Configure stdlib logging and structlog for the application.

    - Production: JSON output for both stdlib and structlog.
    - Local/dev: Human-readable console output.

    structlog wraps the stdlib logger, so all existing `logging.getLogger()`
    calls continue to work unchanged. New code can use `structlog.get_logger()`
    to bind structured context (user_id, request_id, etc.).
    """
    root = logging.getLogger()

    # --- stdlib logging -------------------------------------------------------
    if not root.handlers:
        handler = logging.StreamHandler()
        if settings.environment == "production":
            handler.setFormatter(_JsonFormatter())
        else:
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)-8s %(name)s %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    # --- structlog ------------------------------------------------------------
    shared_processors: list[Any] = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.environment == "production":
        shared_processors.append(structlog.processors.JSONRenderer(ensure_ascii=False))
    else:
        shared_processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


class _JsonFormatter(logging.Formatter):
    """Stdlib formatter that emits JSON lines for production."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _utc_timestamp(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Include request_id when available (set by RequestIDMiddleware)
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)
