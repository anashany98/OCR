"""AI agent tools — domain-specific modules.

This package contains the rule-based tools that the AI agent uses to
answer questions about documents, budgets, orders, invoices, plans, etc.

The original ``internal.py`` was split into domain modules for
maintainability. This ``__init__.py`` re-exports the entire public
surface so existing ``from app.tools import internal`` callers
continue to work unchanged.
"""

from __future__ import annotations

# The ``internal`` module itself is kept as a thin shim that exposes
# the same namespace.  ``from app.tools import internal`` still works.
from app.tools import (  # noqa: F811  (re-export)
    analytics,
    budgets,
    documents,
    invoices,
    orders,
    plans,
    search,
    shipping,
)

# Re-export everything from domain modules for backward compatibility.
# New code should import from the specific domain module directly.
from app.tools.analytics import (
    PRICE_AGGREGATE_KINDS,
    _money_filters,  # noqa: F401  (re-exported for callers that depend on the underscore name)
    aggregate_business,
)
from app.tools.budgets import (
    get_accepted_budgets_without_order,
    get_budget_by_number,
    get_budget_lines,
    get_budget_total,
    get_invoiced_amount_for_budget,
    list_recent_accepted_budgets,
    search_budgets,
)
from app.tools.documents import (
    find_document_by_filename,
    get_document,
    get_document_blocks,
    get_document_full_details,
    get_duplicate_documents,
    get_ocr_review_documents,
    get_related_documents,
    search_documents,
)
from app.tools.invoices import get_invoice_origin_order
from app.tools.orders import (
    get_order_by_number,
    search_orders,
)
from app.tools.plans import (
    get_plan_dimensions,
    get_plan_rooms,
    get_room_measurements,
    search_plan_room_measurements,
    search_plans,
)
from app.tools.search import hybrid_search, search_entities
from app.tools.shipping import (
    SHIPPING_KEYWORDS,
    find_delivery_note_in_scope,
    find_shipping_cost_in_scope,
)

__all__ = [
    # Sub-modules (for ``from app.tools import internal`` compat)
    "analytics",
    "budgets",
    "documents",
    "invoices",
    "orders",
    "plans",
    "search",
    "shipping",
    # Documents
    "search_documents",
    "get_document",
    "get_document_blocks",
    "find_document_by_filename",
    "get_document_full_details",
    "get_related_documents",
    "get_duplicate_documents",
    "get_ocr_review_documents",
    # Budgets
    "search_budgets",
    "get_budget_by_number",
    "get_accepted_budgets_without_order",
    "get_budget_total",
    "get_budget_lines",
    "get_invoiced_amount_for_budget",
    "list_recent_accepted_budgets",
    # Orders
    "search_orders",
    "get_order_by_number",
    # Invoices
    "get_invoice_origin_order",
    # Plans
    "search_plans",
    "get_plan_rooms",
    "get_plan_dimensions",
    "get_room_measurements",
    "search_plan_room_measurements",
    # Search
    "hybrid_search",
    "search_entities",
    # Shipping
    "SHIPPING_KEYWORDS",
    "find_delivery_note_in_scope",
    "find_shipping_cost_in_scope",
    # Analytics
    "PRICE_AGGREGATE_KINDS",
    "aggregate_business",
]
