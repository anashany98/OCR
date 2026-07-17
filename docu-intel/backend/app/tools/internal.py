"""Backward-compatible shim for the original monolithic internal.py.

This module re-exports everything from the domain-specific modules
so existing ``from app.tools.internal import ...`` callers continue
to work unchanged. New code should import from the specific domain
module directly (e.g. ``from app.tools.budgets import get_budget_total``).

The domain modules are:
- documents: Document lookup, details, and relationships
- budgets: Budget-related tools
- orders: Order-related tools
- invoices: Invoice-related tools
- plans: Plan-related tools
- shipping: Shipping and delivery note tools
- search: Search tools
- analytics: Aggregate/analytics tools
"""

from __future__ import annotations

from app.services.project_dossier import (  # noqa: F401
    get_project_communications,
    get_project_dossier,
    get_project_financials,
    get_project_issues,
    get_project_people,
    get_project_products,
    get_project_timeline,
    list_project_documents,
    resolve_project,
    search_project_images,
)

# Re-export everything from domain modules for backward compatibility.
from app.tools.analytics import (  # noqa: F401
    PRICE_AGGREGATE_KINDS,
    _money_filters,
    aggregate_business,
)
from app.tools.dossiers import (  # noqa: F401
    document_count_by_status,
    find_documents_by_reference,
    find_nearest_budget,
    get_budget_summary,
    list_distinct_budget_codes,
    list_documents_by_budget_code,
)
from app.tools.budgets import (  # noqa: F401
    get_accepted_budgets_without_order,
    get_budget_by_number,
    get_budget_lines,
    get_budget_total,
    get_invoiced_amount_for_budget,
    list_recent_accepted_budgets,
    search_budgets,
)
from app.tools.documents import (  # noqa: F401
    find_document_by_filename,
    get_document,
    get_document_blocks,
    get_document_full_details,
    get_duplicate_documents,
    get_ocr_review_documents,
    get_related_documents,
    search_documents,
)
from app.tools.invoices import get_invoice_origin_order  # noqa: F401
from app.tools.orders import (  # noqa: F401
    get_order_by_number,
    search_orders,
)
from app.tools.plans import (  # noqa: F401
    get_plan_cad_context,
    get_plan_dimensions,
    get_plan_rooms,
    get_room_measurements,
    search_plan_room_measurements,
    search_plans,
)
from app.tools.search import hybrid_search, search_entities  # noqa: F401
from app.tools.shipping import (  # noqa: F401
    SHIPPING_KEYWORDS,
    find_delivery_note_in_scope,
    find_shipping_cost_in_scope,
)
