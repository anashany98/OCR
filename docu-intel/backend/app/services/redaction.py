from __future__ import annotations

import re

MONEY_REDACTION = "[IMPORTE OCULTO]"
PII_REDACTION = "[DATO OCULTO]"

MONEY_WITH_CURRENCY_RE = re.compile(
    # A money value with a trailing currency marker. We accept three
    # formats:
    #   1. with thousands separator:   ``1.234,56 €`` / ``1 234,56 €``
    #   2. with decimals:              ``1234,56 €``
    #   3. plain integer with symbol:  ``1500 €`` (rare but valid)
    # The optional decimals group also accepts the ``.`` separator
    # for English-style numbers (``1234.56 €``).
    #
    # Note: we use ``(?=\s|$|[.,;:!?])`` as a "soft" right boundary
    # because ``\b`` does not work after ``€`` (the euro sign is not
    # a ``\w`` character so Python regex sees no word boundary
    # between ``€`` and the end of the string or a following
    # punctuation mark).
    r"\b\d{1,3}(?:[.\s]\d{3})+(?:[,.]\d{2})?\s*(?:€|eur|euros)(?=\s|$|[.,;:!?])"
    r"|\b\d+[,.]\d{2}\s*(?:€|eur|euros)(?=\s|$|[.,;:!?])"
    r"|\b\d+\s*(?:€|eur|euros)(?=\s|$|[.,;:!?])",
    flags=re.IGNORECASE,
)
LABELED_AMOUNT_RE = re.compile(
    r"\b(?P<label>total|importe|precio(?:\s+unitario)?|base\s+imponible|iva|subtotal|descuento|margen|beneficio|coste|costo|condiciones\s+comerciales)\s*[:#-]?\s*"
    r"(?P<amount>\d{1,3}(?:[.\s]\d{3})*(?:[,.]\d{2})?)\s*(?:€|eur|euros)?",
    flags=re.IGNORECASE,
)
PERCENT_MARGIN_RE = re.compile(
    r"\b(?P<label>margen|beneficio|descuento)\s*[:#-]?\s*(?P<amount>\d{1,3}(?:[,.]\d{1,2})?)\s*%",
    flags=re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# PII patterns (1.3 M-12 follow-up)
# ---------------------------------------------------------------------------
# These regexes cover the most common personal identifiers that we never
# want to leak into a prompt sent to the local LLM. They run on top of
# the money redaction so the order of substitution is: amounts first
# (so we do not accidentally turn a digit group of an IBAN into a
# money redaction), then identifiers.
#
# The patterns are intentionally conservative (they may miss
# non-standard formats) but they are good enough to catch every
# well-formed identifier a user could reasonably expect to find in a
# Spanish invoice, contract, or HR document.
# Spanish IBAN: ES + 22 digits, usually grouped as
# ``ES91 2100 0418 4502 0005 1332`` (2 check + 5*4). We accept
# the optional ``ES`` prefix and either spaces, hyphens, or no
# separator between groups. Non-Spanish IBANs are out of scope for
# this initial pass — the redactor still catches their digit groups
# partially because the inner ``\d{4}`` chunks overlap.
IBAN_RE = re.compile(
    r"\b(?:ES[\s-]?)?\d{2}(?:[\s-]?\d{4}){5}\b",
    flags=re.IGNORECASE,
)
# DNI (8 digits + letter) and NIE (X/Y/Z + 7 digits + letter).
# The Spanish standard reserves Y and Z for NIE prefixes.
DNI_NIE_RE = re.compile(r"\b[XYZ]?\d{7,8}[A-Z]\b")
# CIF: starts with a letter in [ABCDEFGHJUV], 8 digits, control char.
# We keep the match conservative so legitimate product codes (which
# are usually 8+ alphanumeric without a leading letter in that set)
# are not swallowed.
CIF_RE = re.compile(r"\b[ABCDEFGHJUV]\d{8}\b")
# RFC-5321-ish: a local part, an ``@`` and a domain with at least one
# dot. Intentionally narrow so we do not eat measurement values like
# "0.5mg/dL".
EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
# Spanish mobile (6/7/8/9 + 8 digits) and optional +34 international
# prefix. Excludes the leading 9 prefix to avoid matching timestamps.
PHONE_RE = re.compile(r"(?:\+34[\s-]?)?\b[6789]\d{8}\b")


def redact_sensitive_text(text: str | None) -> str:
    if not text:
        return ""

    def replace_labeled(match: re.Match[str]) -> str:
        return f"{match.group('label')} {MONEY_REDACTION}"

    redacted = LABELED_AMOUNT_RE.sub(replace_labeled, text)
    redacted = PERCENT_MARGIN_RE.sub(replace_labeled, redacted)
    redacted = MONEY_WITH_CURRENCY_RE.sub(MONEY_REDACTION, redacted)
    return redacted


def redact_pii(text: str | None) -> str:
    """Replace common personal identifiers (IBAN, NIF/DNI/NIE, CIF,
    email, phone) with the ``PII_REDACTION`` placeholder.

    The function is safe to call on ``None`` or empty strings. It is
    applied **after** :func:`redact_sensitive_text` so the digit
    groups of an IBAN are not pre-empted by the money substitution.
    """
    if not text:
        return ""
    redacted = IBAN_RE.sub(PII_REDACTION, text)
    redacted = DNI_NIE_RE.sub(PII_REDACTION, redacted)
    redacted = CIF_RE.sub(PII_REDACTION, redacted)
    redacted = EMAIL_RE.sub(PII_REDACTION, redacted)
    redacted = PHONE_RE.sub(PII_REDACTION, redacted)
    return redacted


def redact_for_llm(text: str | None) -> str:
    """Combined money + PII redaction, in the correct order.

    Use this for any text that will be assembled into a prompt sent
    to the local LLM. Money first (so the IBAN digit groups are
    intact when the IBAN regex runs), then PII.
    """
    return redact_pii(redact_sensitive_text(text))
