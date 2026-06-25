"""CTX-3 — Resolve follow-up references with the active conversation state.

The orchestrator calls :func:`resolve_references` with the raw user
question and the :class:`app.ai.active_context.ActiveContext`. The
function returns:

* ``resolved_question`` — the question rewritten to include the active
  context in a way the LLM and the tool selector can both consume. We
  append a small ``[Contexto: ...]`` block at the start so the original
  sentence is preserved (the system prompt instructs the LLM to
  treat that block as data, not as instructions).
* ``resolution`` — a small dict with the entities we detected. The
  scope guard and the intent router consume it to pin the request to
  the active budget / document / invoice. Keys:
    - ``budget_number``, ``budget_id``, ``client_name``
    - ``document_id``, ``document_path``
    - ``invoice_number``, ``order_number``, ``delivery_note_number``
    - ``referenced_entity`` — one of ``budget``, ``order``, ``invoice``,
      ``document``, ``folder``, ``plan``, ``none``.
    - ``rewrote`` — True when the resolver actually injected context
      (used in tests and in the answer header so the user can see that
      the system understood the follow-up).

The reference patterns cover the examples the user gave in the task
brief and the Spanish business jargon we see in real conversations
(``"este presupuesto"``, ``"el pedido"``, ``"el albarán"``, …). Patterns
are matched after :func:`_normalize` so accents and casing are
irrelevant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from .active_context import ActiveContext

# ---------------------------------------------------------------------------
# Reference lexicon
# ---------------------------------------------------------------------------
# Each entry is a (regex, kind, prefer_state_key) tuple. The regex is
# matched against the normalised (lowercased, accent-stripped) question
# and the kind is the entity the pattern refers to. ``prefer_state_key``
# names which ActiveContext field should be used to resolve the
# reference when the kind matches.


_REFERENCE_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    # Budgets
    (
        re.compile(r"\b(este|el|ese|ese mismo|el mismo)\s+presupuesto\b"),
        "budget",
        "current_budget_number",
    ),
    (re.compile(r"\bde\s+este\s+presupuesto\b"), "budget", "current_budget_number"),
    (re.compile(r"\bpor\s+cuanto\s+esta\s+presupuestad[oa]\b"), "budget", "current_budget_number"),
    (
        re.compile(r"\bcuanto\s+(se\s+)?ha\s+facturad[oa]\s+(de|del)\b"),
        "budget",
        "current_budget_number",
    ),
    (re.compile(r"\bque\s+lineas\s+tiene\s+(este|el)\b"), "budget", "current_budget_number"),
    (re.compile(r"\bimporte\s+total\s+del\s+presupuesto\b"), "budget", "current_budget_number"),
    # Orders
    (re.compile(r"\b(este|el|ese)\s+pedido\b"), "order", "current_order_number"),
    (re.compile(r"\bque\s+pedido\s+origino\s+esta\s+factura\b"), "order", "current_order_number"),
    (re.compile(r"\bel\s+pedido\s+origen\b"), "order", "current_order_number"),
    # Invoices
    (re.compile(r"\b(esta|la|esa)\s+factura\b"), "invoice", "current_invoice_number"),
    (re.compile(r"\b(esta|la|esa)\s+proforma\b"), "invoice", "current_invoice_number"),
    # Delivery notes (albaranes)
    (re.compile(r"\bel\s+albaran\b"), "delivery_note", "current_delivery_note_number"),
    (re.compile(r"\bel\s+envio\b"), "delivery_note", "current_delivery_note_number"),
    (
        re.compile(r"\bdispon(es|es)\s+del\s+albaran\b"),
        "delivery_note",
        "current_delivery_note_number",
    ),
    (re.compile(r"\b(este|el|ese)\s+albaran\b"), "delivery_note", "current_delivery_note_number"),
    # Plans / drawings
    (re.compile(r"\b(este|el|ese)\s+plano\b"), "plan", "current_document_path"),
    (re.compile(r"\bde\s+que\s+trata\s+el\s+plano\b"), "plan", "current_document_path"),
    # Generic documents
    (re.compile(r"\b(este|el|ese)\s+documento\b"), "document", "current_document_path"),
    (re.compile(r"\b(esta|la|esa)\s+carpeta\b"), "folder", "current_folder_path"),
    (re.compile(r"\bde\s+este\s+"), "budget", "current_budget_number"),
    (re.compile(r"\bde\s+esta\s+"), "folder", "current_folder_path"),
)


_NORMALIZE_TABLE = str.maketrans(
    "áéíóúüñ¿¡",
    "aeiouun  ",
)


def _normalize(text: str) -> str:
    """Lightweight lowercase + accent-strip. Shared with ``tools._normalize``."""
    lowered = (text or "").lower()
    return lowered.translate(_NORMALIZE_TABLE)


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedReference:
    """The result of resolving a single follow-up reference."""

    referenced_entity: str
    budget_number: str | None = None
    budget_id: int | None = None
    client_name: str | None = None
    document_id: int | None = None
    document_path: str | None = None
    invoice_number: str | None = None
    order_number: str | None = None
    delivery_note_number: str | None = None
    folder_path: str | None = None
    rewrote: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "referenced_entity": self.referenced_entity,
            "budget_number": self.budget_number,
            "budget_id": self.budget_id,
            "client_name": self.client_name,
            "document_id": self.document_id,
            "document_path": self.document_path,
            "invoice_number": self.invoice_number,
            "order_number": self.order_number,
            "delivery_note_number": self.delivery_note_number,
            "folder_path": self.folder_path,
            "rewrote": self.rewrote,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_reference(question: str) -> tuple[str, str] | None:
    """Return ``(kind, prefer_state_key)`` if ``question`` contains a
    follow-up reference we can resolve, else ``None``.

    Multiple patterns can match. The first one wins (the patterns are
    ordered from most specific to most generic).
    """
    normalized = _normalize(question)
    for pattern, kind, prefer_key in _REFERENCE_PATTERNS:
        if pattern.search(normalized):
            return kind, prefer_key
    return None


def resolve_references(
    question: str,
    state: ActiveContext,
) -> tuple[str, ResolvedReference]:
    """Rewrite ``question`` to make the active context explicit.

    Always returns a tuple. When the question does not contain a
    follow-up reference, the original question is returned untouched
    and the resolution is a no-op (``referenced_entity="none"``,
    ``rewrote=False``).

    The rewrite is additive, not destructive. The original sentence is
    preserved so the LLM still sees the user's natural phrasing; the
    active context is prepended in a single ``[Contexto: ...]`` block
    the system prompt already tells the LLM to treat as data.
    """
    original = (question or "").strip()
    if not original:
        return original, ResolvedReference(referenced_entity="none")

    detected = detect_reference(original)
    if detected is None:
        return original, ResolvedReference(referenced_entity="none")

    kind, prefer_key = detected
    state_value = getattr(state, prefer_key, None) if prefer_key else None

    # Build the resolution payload with the relevant subset of the
    # state. We always copy the full trio (number, id, client) so the
    # downstream consumers (scope guard, intent router) have everything
    # they might need without having to consult the state again.
    resolution = ResolvedReference(
        referenced_entity=kind,
        budget_number=state.current_budget_number,
        budget_id=state.current_budget_id,
        client_name=state.current_client_name,
        document_id=state.current_document_id,
        document_path=state.current_document_path,
        invoice_number=state.current_invoice_number,
        order_number=state.current_order_number,
        delivery_note_number=state.current_delivery_note_number,
        folder_path=state.current_folder_path,
    )

    # If the state has nothing to resolve the reference, we still
    # return the original question (no rewrite) and a no-op resolution
    # so the orchestrator can fall through to the existing behaviour
    # (which will warn the user that the conversation context is empty).
    state_has_anything = (
        state_value
        or state.has_budget_scope
        or state.current_document_id
        or state.current_invoice_number
        or state.current_order_number
        or state.current_delivery_note_number
        or state.current_folder_path
    )
    if not state_has_anything:
        return original, ResolvedReference(referenced_entity="none")

    # Build the [Contexto: ...] block from the non-empty state fields.
    # We always include the active budget / folder / client (they are
    # the most useful context for the LLM regardless of the kind) and
    # add the entity-specific number only when it is the one the user
    # asked about.
    context_parts: list[str] = []
    if state.current_budget_number:
        context_parts.append(f"presupuesto {state.current_budget_number}")
    if state.current_client_name:
        context_parts.append(f"cliente {state.current_client_name}")
    if state.current_folder_path:
        context_parts.append(f"carpeta {state.current_folder_path}")
    # Include the entity-specific reference when:
    # - the kind matches (the user is asking about that entity), OR
    # - the active context HAS that entity and the user is asking
    #   about a related one (e.g. "que pedido origino esta factura"
    #   with state.invoice_number = F-200 should inject the invoice
    #   number so the LLM can look it up).
    if state.current_invoice_number and kind in {"invoice", "order"}:
        context_parts.append(f"factura {state.current_invoice_number}")
    if state.current_order_number and kind in {"order", "invoice"}:
        context_parts.append(f"pedido {state.current_order_number}")
    if state.current_delivery_note_number and kind == "delivery_note":
        context_parts.append(f"albaran {state.current_delivery_note_number}")
    if state.current_document_path and kind in {"document", "plan"}:
        context_parts.append(f"documento {state.current_document_path}")
    if not context_parts:
        return original, ResolvedReference(referenced_entity="none")

    rewritten = f"[Contexto: {', '.join(context_parts)}] {original}"
    return rewritten, replace(resolution, rewrote=True)
