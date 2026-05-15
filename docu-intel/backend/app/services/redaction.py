from __future__ import annotations

import re

MONEY_REDACTION = "[IMPORTE OCULTO]"

MONEY_WITH_CURRENCY_RE = re.compile(
    r"\b\d{1,3}(?:[.\s]\d{3})*(?:[,.]\d{2})?\s*(?:€|eur|euros)\b",
    flags=re.IGNORECASE,
)
LABELED_AMOUNT_RE = re.compile(
    r"\b(?P<label>total|importe|precio(?:\s+unitario)?|base\s+imponible|iva)\s*[:#-]?\s*"
    r"(?P<amount>\d{1,3}(?:[.\s]\d{3})*(?:[,.]\d{2})?)\s*(?:€|eur|euros)?",
    flags=re.IGNORECASE,
)


def redact_sensitive_text(text: str | None) -> str:
    if not text:
        return ""

    def replace_labeled(match: re.Match[str]) -> str:
        return f"{match.group('label')} {MONEY_REDACTION}"

    redacted = LABELED_AMOUNT_RE.sub(replace_labeled, text)
    redacted = MONEY_WITH_CURRENCY_RE.sub(MONEY_REDACTION, redacted)
    return redacted
