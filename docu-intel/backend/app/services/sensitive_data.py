"""Phase 10 — Sensitive data redaction.

Detects and redacts sensitive information (IBAN, NIF/CIF, accounts,
emails, phones, amounts) based on user permissions. Applied BEFORE
data is returned to the user, not after.
"""

from __future__ import annotations

import re
from typing import Any

# Regex patterns for sensitive data detection
_IBAN_PATTERN = re.compile(
    r"\b[A-Z]{2}\d{2}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{0,4}\b",
    re.IGNORECASE,
)
_NIF_CIF_PATTERN = re.compile(
    r"\b[0-9]{8}[A-Z]\b|\b[A-Z][0-9]{7}[A-Z0-9]\b",
    re.IGNORECASE,
)
_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?34[\s-]?)?[6-9]\d{2}[\s.-]?\d{3}[\s.-]?\d{3}(?!\d)",
)
_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
)
_AMOUNT_PATTERN = re.compile(
    r"\b(?:\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?\s*(?:EUR|€|USD|\$|GBP|£)"
    r"|(?:EUR|€|USD|\$|GBP|£)\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\b",
)
_ACCOUNT_PATTERN = re.compile(
    r"\b\d{4}[\s.-]?\d{4}[\s.-]?\d{4}[\s.-]?\d{4}\b",
)


def detect_sensitive_data(text: str) -> list[dict[str, Any]]:
    """Detect sensitive data patterns in text.

    Returns list of {type, value, start, end, confidence}.
    """
    findings = []
    for pattern, label, conf in [
        (_IBAN_PATTERN, "iban", 0.9),
        (_NIF_CIF_PATTERN, "nif_cif", 0.8),
        (_PHONE_PATTERN, "phone", 0.7),
        (_EMAIL_PATTERN, "email", 0.95),
        (_ACCOUNT_PATTERN, "account_number", 0.6),
    ]:
        for m in pattern.finditer(text):
            findings.append({
                "type": label,
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": conf,
            })

    # Amount patterns
    for m in _AMOUNT_PATTERN.finditer(text):
        findings.append({
            "type": "amount",
            "value": m.group(),
            "start": m.start(),
            "end": m.end(),
            "confidence": 0.85,
        })

    findings.sort(key=lambda x: x["start"])
    return findings


def redact_text(text: str, *, redact_amounts: bool = True, redact_pii: bool = True) -> str:
    """Redact sensitive data from text based on policy.

    Args:
        text: Original text
        redact_amounts: Whether to redact monetary amounts
        redact_pii: Whether to redact PII (IBAN, NIF, emails, phones)
    """
    if not text:
        return text

    # Work backwards to preserve indices
    findings = detect_sensitive_data(text)
    result = text
    for f in reversed(findings):
        ftype = f["type"]
        if ftype == "amount" and not redact_amounts:
            continue
        if ftype in ("iban", "nif_cif", "phone", "email", "account_number") and not redact_pii:
            continue
        replacement = f"[{ftype.upper()}_REDACTED]"
        result = result[:f["start"]] + replacement + result[f["end"]:]

    return result


def redact_dict_payload(
    payload: dict[str, Any],
    *,
    redact_amounts: bool = True,
    redact_pii: bool = True,
    fields_to_check: list[str] | None = None,
) -> dict[str, Any]:
    """Redact sensitive data from string values in a dict payload."""
    if not payload:
        return payload

    result = dict(payload)
    check_fields = fields_to_check or list(result.keys())

    for key in check_fields:
        if key in result and isinstance(result[key], str):
            result[key] = redact_text(
                result[key],
                redact_amounts=redact_amounts,
                redact_pii=redact_pii,
            )
    return result


def redact_for_scope(
    payload: dict[str, Any],
    can_view_prices: bool,
    is_admin: bool = False,
) -> dict[str, Any]:
    """Redact a payload based on user scope.

    Non-price-viewing users get amounts hidden.
    Non-admin users get PII redacted.
    """
    result = dict(payload)
    # Always redact PII for non-admins
    if not is_admin:
        for key in list(result.keys()):
            if isinstance(result[key], str):
                result[key] = redact_text(result[key], redact_amounts=False, redact_pii=True)
    # Redact amounts for users who can't view prices
    if not can_view_prices:
        for key in list(result.keys()):
            if isinstance(result[key], str):
                result[key] = redact_text(result[key], redact_amounts=True, redact_pii=False)
            elif isinstance(result[key], (int, float)) and key.endswith(("_amount", "_price", "_total", "_cost")):
                result[key] = None
    return result
