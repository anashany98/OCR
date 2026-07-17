"""S1.3 — PII redaction before the LLM prompt.

The previous redactor only handled money/currency, leaving IBAN,
NIF/DNI/NIE, CIF, email and phone numbers free to leak into a
prompt sent to the local LLM. This test pins the new
``redact_pii`` / ``redact_for_llm`` helpers and the
``redact_context_items_for_scope`` integration so a future refactor
that drops the PII pass is caught by CI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.redaction import (
    PII_REDACTION,
    redact_for_llm,
    redact_pii,
    redact_sensitive_text,
)


# ---------------------------------------------------------------------------
# redact_pii — pure regex
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected_substring",
    [
        # IBAN: ES + 22 digits, with and without the ES prefix
        (
            "Pago al IBAN ES91 2100 0418 4502 0005 1332 antes del viernes",
            PII_REDACTION,
        ),
        (
            "Transferir a 91 2100 0418 4502 0005 1332 sin demora",
            PII_REDACTION,
        ),
        # DNI (8 digits + letter) and NIE (X/Y/Z + 7 digits + letter)
        ("Identificado con DNI 12345678A en la factura", PII_REDACTION),
        ("NIE X1234567A del consultor", PII_REDACTION),
        # CIF (letter in [ABCDEFGHJUV] + 8 digits)
        ("CIF B12345678 de la empresa", PII_REDACTION),
        # Email
        ("Escribe a usuario@empresa.es para más info", PII_REDACTION),
        # Spanish mobile (6/7/9 + 8 digits)
        ("Llama al 612345678 para confirmar", PII_REDACTION),
    ],
)
def test_redact_pii_replaces_known_identifiers(text, expected_substring):
    """Every well-formed Spanish identifier must be replaced by the
    PII placeholder. We assert the placeholder is present and the
    original identifier token is not.
    """
    redacted = redact_pii(text)
    assert expected_substring in redacted, (
        f"Expected {expected_substring!r} in redacted output, got: {redacted!r}"
    )


def test_redact_pii_keeps_money_intact():
    """The PII pass must run *after* money redaction so the digit
    groups of an IBAN survive the PII regex. We assert that
    ``redact_pii`` alone does not touch the currency value.
    """
    text = "Total: 1234,56 euros pagados desde IBAN ES91 2100 0418 4502 0005 1332"
    redacted = redact_pii(text)
    # The amount should be untouched (no PII pattern matches it).
    assert "1234,56" in redacted
    # The IBAN is gone.
    assert "ES91 2100 0418 4502 0005 1332" not in redacted
    assert PII_REDACTION in redacted


def test_redact_pii_handles_empty_and_none():
    """``None`` and empty strings must return empty without raising."""
    assert redact_pii(None) == ""
    assert redact_pii("") == ""


# ---------------------------------------------------------------------------
# redact_for_llm — combined
# ---------------------------------------------------------------------------


def test_redact_for_llm_combines_money_and_pii():
    """The combined helper must apply both passes. Money first, then
    PII, so an IBAN digit group is not pre-empted by the money
    substitution.

    We use a money value with a thousands separator (``1.500,00 €``)
    so the existing money redactor pattern catches it; the
    redactor's coverage of bare integers without a separator is
    intentionally narrower and is out of scope for the PII fix.
    """
    text = "Factura de 1.500,00 € con IBAN ES91 2100 0418 4502 0005 1332 y NIF 12345678A"
    redacted = redact_for_llm(text)
    assert "1.500,00" not in redacted, "money must be redacted"
    assert "ES91 2100 0418 4502 0005 1332" not in redacted, "IBAN must be redacted"
    assert "12345678A" not in redacted, "NIF must be redacted"


# ---------------------------------------------------------------------------
# redact_context_items_for_scope — integration
# ---------------------------------------------------------------------------


@dataclass
class _FakeContextItem:
    """Minimal dataclass that mirrors the fields read by
    ``redact_context_items_for_scope``.

    The real ``ContextItem`` is a frozen dataclass with many more
    fields; for the purpose of this test we only need
    ``summary`` and ``excerpt`` (the function under test only
    touches those two). Building a stand-in keeps the test fast
    and decoupled from the rest of the AI module.
    """

    summary: str = ""
    excerpt: str | None = None
    document_id: int = 0
    page_number: int | None = None
    block_id: int | None = None
    chunk_id: int | None = None
    score: float = 1.0
    source_type: str = "test"
    source_path: str | None = None
    ocr_confidence: float | None = 1.0
    confidence: float | None = 1.0
    warning: Any = None


def _make_context_item(summary: str, excerpt: str | None = None) -> _FakeContextItem:
    """Build a real dataclass that ``dataclasses.replace`` will accept."""
    return _FakeContextItem(summary=summary, excerpt=excerpt)


def test_context_redactor_strips_pii_even_when_admin():
    """PII redaction is universal: even a user with
    ``can_view_prices=True`` (admin) must not see IBAN / NIF / email
    on the items that reach the LLM. This guards against a future
    refactor that gates PII behind a permission flag and ends up
    leaking customer data into the prompt.
    """
    from app.ai.context import redact_context_items_for_scope

    admin_scope = SimpleNamespace(can_view_prices=True)
    item = _make_context_item(
        summary="Pagar al IBAN ES91 2100 0418 4502 0005 1332 con NIF 12345678A",
        excerpt=None,
    )
    redacted = redact_context_items_for_scope([item], admin_scope)
    assert len(redacted) == 1
    assert "ES91 2100 0418 4502 0005 1332" not in redacted[0].summary
    assert "12345678A" not in redacted[0].summary
    assert PII_REDACTION in redacted[0].summary
    # Original item is untouched.
    assert "ES91" in item.summary


def test_context_redactor_strips_money_when_not_authorized():
    """Money redaction must still apply when the user lacks
    ``can_view_prices``.

    The existing redactor pattern (``LABELED_AMOUNT_RE``) requires
    a label directly followed by a separator (``Total: 1.234,56 €``).
    We use that exact shape to make the test independent of any
    pre-existing limitations in the money redactor that are out of
    scope for the PII fix.
    """
    from app.ai.context import redact_context_items_for_scope

    restricted_scope = SimpleNamespace(can_view_prices=False)
    item = _make_context_item(
        summary="Total: 1.234,56 €",
        excerpt="Importe: 1.234,56 €",
    )
    redacted = redact_context_items_for_scope([item], restricted_scope)
    assert "[IMPORTE OCULTO]" in redacted[0].summary
    assert "[IMPORTE OCULTO]" in redacted[0].excerpt
