from __future__ import annotations

import hmac
import json
import logging
from hashlib import sha256
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def emit_integration_webhook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not settings.integration_webhook_url:
        return {"sent": False, "reason": "webhook_not_configured"}
    if event not in settings.integration_webhook_events:
        return {"sent": False, "reason": "event_disabled"}
    body = {"event": event, "payload": payload}
    headers = {"Content-Type": "application/json"}
    if settings.integration_webhook_secret:
        headers["X-DocuIntel-Signature"] = _signature(body)
    try:
        response = httpx.post(settings.integration_webhook_url, json=body, headers=headers, timeout=5.0)
        response.raise_for_status()
        return {"sent": True, "status_code": response.status_code}
    except Exception as exc:
        logger.warning("integration_webhook_failed event=%s error=%s", event, exc)
        return {"sent": False, "reason": str(exc)}


def build_webhook_test_payload() -> dict[str, Any]:
    return {
        "event": "docuintel.webhook_test",
        "payload": {
            "message": "Webhook de prueba desde Docu-Intel",
        },
    }


def _signature(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(settings.integration_webhook_secret.encode("utf-8"), raw, sha256).hexdigest()
    return f"sha256={digest}"
