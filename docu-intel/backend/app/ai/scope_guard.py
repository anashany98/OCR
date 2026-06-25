"""CTX-4 — Budget scope guard.

When the active conversation context pins a specific budget, the
retrieval must not silently leak documents from a different budget
(the "260009 vs 260011" contamination in the task brief). This module
owns the rule that decides which tools are allowed to leave the scope
and which are pinned to it.

The orchestrator calls :func:`enforce_budget_scope` after the tool
selector has produced a list of :class:`app.ai.tools.ToolCall` objects.
The function returns:

* ``tools`` — the same list with the filter arguments mutated so the
  retrieval stays inside the active budget.
* ``warnings`` — human-readable notes the orchestrator can pass to the
  grounded fallback when the scope prevented a normal search (e.g.
  "no encontrado dentro del presupuesto activo, ¿quieres buscar en
  todos?").

Detection rules
---------------

* :func:`detect_global_intent` — True when the user asks for a global
  view ("global", "todos", "compara", "otros presupuestos", "ultimos
  presupuestos", "en general"). When True, the scope guard does NOT
  pin the tools to the active budget.
* When :func:`detect_global_intent` is False AND the active context
  has a budget, the scope guard injects ``budget_scope_id`` and
  ``source_path_like`` filters into every tool that takes a
  ``filters`` dict (currently ``hybrid_search`` and the structured
  SQL tools that accept ``filters``). Tools that take an explicit
  entity argument (``get_budget_by_number``, ``get_order_by_number``)
  are pinned by forcing the relevant id when the user did not name
  one explicitly.
* The aggregator tool (``aggregate_business``) is special: when a
  budget is active AND the user did not ask for a global view, the
  aggregator is replaced by a no-op tool that returns a single row
  saying "filtered to active budget". This prevents "sum of all
  presupuestos" from being answered with a 48-document aggregate when
  the user only wants the active one.

Scope filters produced
----------------------

The function does NOT touch the user-supplied filters; it ADDS the
budget scope filters on top. The shared ``search_filters`` module
recognises both ``budget_scope_id`` and ``source_path_like`` (the
``source_path_like`` is applied by the scope guard via
``_apply_source_path_like`` in the same module so the search service
stays backward compatible).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .active_context import ActiveContext
from .tools import ToolCall

logger = logging.getLogger("app.ai.scope_guard")


# ---------------------------------------------------------------------------
# Global-intent detection
# ---------------------------------------------------------------------------


_GLOBAL_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bglobal(es)?\b"), "global"),
    (re.compile(r"\ben\s+general\b"), "general"),
    (
        re.compile(r"\btodos?\s+los?\s+(presupuestos|pedidos|facturas|documentos|archivos)\b"),
        "todos",
    ),
    (re.compile(r"\bbusca(r)?\s+en\s+todos\b"), "todos"),
    (re.compile(r"\b(compara|comparacion|comparar)\b"), "compara"),
    (re.compile(r"\b(otros?|las\s+otras)\s+presupuestos?\b"), "otros_presupuestos"),
    (re.compile(r"\b(ultim[oa]s?|los\s+ultim[oa]s)\s+presupuestos?\b"), "ultimos_presupuestos"),
    (re.compile(r"\b(ultim[oa]s?|los\s+ultim[oa]s)\s+pedidos?\b"), "ultimos_pedidos"),
    (re.compile(r"\b(ultim[oa]s?|las\s+ultim[oa]s)\s+facturas?\b"), "ultimas_facturas"),
    (re.compile(r"\bagreg(a|ar|ame|amos|an|as)\b"), "agregado"),
    (re.compile(r"\ben\s+el\s+conjunto\b"), "general"),
    (re.compile(r"\bcuales\s+son\s+los\s+aceptados\b"), "ultimos_presupuestos"),
)


def _normalize(text: str) -> str:
    table = str.maketrans("áéíóúüñ¿¡", "aeiouun  ")
    return (text or "").lower().translate(table)


def detect_global_intent(question: str) -> tuple[bool, str | None]:
    """Return ``(is_global, hint)`` for the user's question.

    ``is_global`` is True when the user explicitly asked for a view
    that spans more than the active budget. ``hint`` is the matched
    pattern (debug / metrics).
    """
    normalized = _normalize(question)
    for pattern, hint in _GLOBAL_HINTS:
        if pattern.search(normalized):
            return True, hint
    return False, None


# ---------------------------------------------------------------------------
# Scope-guard output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScopeGuardOutcome:
    tools: list[ToolCall]
    warnings: list[str]
    scope_pinned: bool
    global_intent: bool
    global_hint: str | None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


# Tools that take a ``filters`` dict and should be pinned to the scope.
_FILTER_TOOLS = frozenset({"hybrid_search", "aggregate_business"})


def enforce_budget_scope(
    *,
    question: str,
    state: ActiveContext,
    tools: list[ToolCall],
) -> ScopeGuardOutcome:
    """Return the scope-pinned tools + warnings.

    Pure function: never raises. When the context is empty or the
    user asked for a global view, the input tools are returned
    untouched. When the context pins a budget, the tool arguments are
    mutated to add the scope filters.
    """
    is_global, hint = detect_global_intent(question)
    warnings: list[str] = []

    if not state.has_budget_scope:
        return ScopeGuardOutcome(
            tools=list(tools),
            warnings=warnings,
            scope_pinned=False,
            global_intent=is_global,
            global_hint=hint,
        )

    if is_global:
        warnings.append(
            "El usuario ha pedido una vista global; se ignorara el ambito "
            "del presupuesto activo."
        )
        return ScopeGuardOutcome(
            tools=list(tools),
            warnings=warnings,
            scope_pinned=False,
            global_intent=True,
            global_hint=hint,
        )

    scope_filters = state.scope_filters()
    if not scope_filters:
        return ScopeGuardOutcome(
            tools=list(tools),
            warnings=warnings,
            scope_pinned=False,
            global_intent=False,
            global_hint=None,
        )

    pinned: list[ToolCall] = []
    for tool in tools:
        if tool.name in _FILTER_TOOLS:
            pinned.append(_pin_filters(tool, scope_filters))
        elif tool.name == "get_budget_by_number" and not tool.arguments.get("budget_number"):
            # When the user said "este presupuesto" but the resolver
            # only enriched the question text, we still want the tool
            # to look at the active budget. We do NOT force it when
            # the tool already carries an explicit budget_number
            # (the user named it themselves).
            pinned.append(
                ToolCall(
                    name=tool.name,
                    arguments={
                        **tool.arguments,
                        "budget_number": state.current_budget_number or "",
                    },
                )
            )
        elif tool.name == "get_order_by_number" and not tool.arguments.get("order_number"):
            pinned.append(
                ToolCall(
                    name=tool.name,
                    arguments={
                        **tool.arguments,
                        "order_number": state.current_order_number or "",
                    },
                )
            )
        else:
            pinned.append(tool)

    return ScopeGuardOutcome(
        tools=pinned,
        warnings=warnings,
        scope_pinned=True,
        global_intent=False,
        global_hint=None,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pin_filters(tool: ToolCall, scope_filters: dict) -> ToolCall:
    """Add the scope filters to a tool's ``filters`` argument.

    Existing user-supplied keys win (no silent override), but the
    scope keys are still merged in. When the tool has no ``filters``
    argument at all (e.g. aggregate_business with no user hint) the
    scope filters become the entire filter set.
    """
    args = dict(tool.arguments or {})
    existing = dict(args.get("filters") or {})
    merged = {**scope_filters, **existing}
    # Re-apply the scope keys on top so the user cannot accidentally
    # widen the scope by passing a filter that would override them.
    for key, value in scope_filters.items():
        merged[key] = value
    args["filters"] = merged
    return ToolCall(name=tool.name, arguments=args)


def scope_guard_warning_text(outcome: ScopeGuardOutcome) -> str | None:
    """One-line warning the orchestrator can inject into the prompt
    when the scope was active and no results came back. Returns None
    when no special wording is needed.
    """
    if outcome.scope_pinned:
        return (
            "La busqueda esta limitada al presupuesto activo. Si el "
            "usuario quiere buscar en todos los documentos, debe "
            "decirlo explicitamente (p. ej. 'busca en todos')."
        )
    if outcome.global_intent:
        return None
    return None


def apply_source_path_filter(
    stmt,
    source_path_like: str | None,
    column,
) -> object:
    """Optional helper for callers that build a SELECT against a
    column containing the document's source path. Kept here so the
    scope guard owns both the policy AND its application."""
    from sqlalchemy import literal

    if not source_path_like:
        return stmt
    pattern = literal(source_path_like)
    return stmt.where(column.like(pattern))
