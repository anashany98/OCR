"""Aggregate / analytics tools for the AI agent.

Used to answer questions like "cuanto nos hemos gastado en X" or
"cuantos pedidos hay sin factura".
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Budget, Invoice, Order
from app.services.search_service import _escape_ilike_wildcards
from app.services.tenant_access import AccessScope, filter_records_by_document_scope

PRICE_AGGREGATE_KINDS = {"total", "top", "by_supplier", "period"}


def _money_filters(kind: str, query: str) -> dict[str, Any]:
    """Pull a number, supplier/client/period hint out of a Spanish natural
    language query, so the aggregate queries can be filtered without the LLM
    having to translate its answer into SQL itself."""
    q = (query or "").lower()
    filters: dict[str, Any] = {}

    # Supplier / client name: look for "proveedor X", "del proveedor X",
    # "cliente X", "del cliente X". Take the rest of the sentence.
    m = re.search(
        r"(?:proveedor|proveedores)\s+(?:de\s+|del\s+|de la\s+)?([\wÀ-ſ &./'-]{2,60})",
        q,
    )
    if m:
        filters["supplier"] = m.group(1).strip(" .?!,;:")

    m = re.search(
        r"(?:cliente|clientes)\s+(?:de\s+|del\s+|de la\s+)?([\wÀ-ſ &./'-]{2,60})",
        q,
    )
    if m:
        filters["client"] = m.group(1).strip(" .?!,;:")

    # Numeric threshold: "mas de 10000", "que superan los 5000", "< 200",
    # "mayores a 1000".
    m = re.search(
        r"(?:mas de|mayores? a|superan?|por encima de|>)\s*(\d+(?:[.,]\d+)*)",
        q,
    )
    if m:
        filters["amount_min"] = float(m.group(1).replace(",", "."))
    m = re.search(
        r"(?:menos de|menores? a|por debajo de|<)\s*(\d+(?:[.,]\d+)*)",
        q,
    )
    if m:
        filters["amount_max"] = float(m.group(1).replace(",", "."))

    # Status / acceptance flags.
    if any(w in q for w in ["aceptad", "aprobad"]):
        filters["accepted"] = True
    if any(w in q for w in ["no aceptad", "rechazad", "pendiente de aceptar"]):
        filters["accepted"] = False
    if any(w in q for w in ["sin facturar", "sin factura", "no facturad"]):
        filters["invoiced"] = False
    if any(w in q for w in ["facturad", "con factura"]):
        filters["invoiced"] = True
    if any(w in q for w in ["sin pedido", "sin pedidos", "no tiene pedido"]):
        filters["has_order"] = False
    if any(w in q for w in ["con pedido"]):
        filters["has_order"] = True

    # Period / year: "este ano", "en 2024", "este mes".
    year_match = re.search(r"\b(20\d{2})\b", q)
    if year_match:
        filters["year"] = int(year_match.group(1))
    elif "este ano" in q or "este año" in q:
        filters["year"] = date.today().year
    elif "ano pasado" in q or "año pasado" in q:
        filters["year"] = date.today().year - 1
    elif "este mes" in q:
        filters["year"] = date.today().year
        filters["month"] = date.today().month

    return filters


def _budget_aggregate(
    db: Session,
    kind: str,
    filters: dict[str, Any],
    access_scope: AccessScope | None = None,
) -> list[dict[str, Any]]:
    """Build aggregate results for `kind` in {total, count, top, period}
    restricted to `Budget` records with the given filters.
    F5-05: uses SQL aggregation for count/total instead of Python sum."""

    stmt = select(Budget)
    if filters.get("client"):
        stmt = stmt.where(
            Budget.client_name.ilike(f"%{_escape_ilike_wildcards(filters['client'])}%")
        )
    if filters.get("amount_min") is not None:
        stmt = stmt.where(Budget.total_amount >= filters["amount_min"])
    if filters.get("amount_max") is not None:
        stmt = stmt.where(Budget.total_amount <= filters["amount_max"])
    if filters.get("accepted") is True:
        stmt = stmt.where(Budget.accepted_detected.is_(True))
    elif filters.get("accepted") is False:
        stmt = stmt.where(Budget.accepted_detected.is_(False))
    if filters.get("has_order") is False:
        ordered_ids = select(Order.related_budget_id).where(Order.related_budget_id.is_not(None))
        stmt = stmt.where(Budget.id.not_in(ordered_ids))

    # F5-05: for count/total, use SQL aggregation with scope filter
    if kind == "count" and access_scope is None:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_val = db.scalar(count_stmt) or 0
        return [
            {
                "metric": "count",
                "value": count_val,
                "label": "presupuestos que cumplen los filtros",
            }
        ]
    if kind == "total" and access_scope is None:
        total_stmt = select(func.coalesce(func.sum(Budget.total_amount), 0.0)).select_from(
            stmt.subquery()
        )
        total_val = float(db.scalar(total_stmt) or 0.0)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_val = db.scalar(count_stmt) or 0
        return [
            {
                "metric": "total_amount",
                "value": round(total_val, 2),
                "label": "suma de importes de presupuestos",
                "count": count_val,
            }
        ]

    # Fallback: fetch and aggregate in Python (needed for scoped queries)
    budgets = list(db.scalars(stmt).all())
    if access_scope is not None:
        budgets = filter_records_by_document_scope(db, budgets, access_scope)

    if kind == "count":
        return [
            {
                "metric": "count",
                "value": len(budgets),
                "label": "presupuestos que cumplen los filtros",
            }
        ]
    if kind == "total":
        total = sum((b.total_amount or 0.0) for b in budgets if b.total_amount is not None)
        return [
            {
                "metric": "total_amount",
                "value": round(total, 2),
                "label": "suma de importes de presupuestos",
                "count": len(budgets),
            }
        ]
    if kind == "top":
        sorted_bs = sorted(budgets, key=lambda b: b.total_amount or 0, reverse=True)[:10]
        return [
            {
                "metric": "top_presupuesto",
                "value": b.total_amount,
                "label": (
                    f"Presupuesto {b.budget_number or b.id} - cliente {b.client_name or '-'} - "
                    f"{b.total_amount or 0:.2f} {b.currency or ''} - estado {b.status or '-'}"
                ).strip(),
                "document_id": b.document_id,
            }
            for b in sorted_bs
        ]
    return []


def _order_aggregate(
    db: Session,
    kind: str,
    filters: dict[str, Any],
    access_scope: AccessScope | None = None,
) -> list[dict[str, Any]]:
    stmt = select(Order)
    if filters.get("supplier"):
        stmt = stmt.where(
            Order.supplier_name.ilike(f"%{_escape_ilike_wildcards(filters['supplier'])}%")
        )
    if filters.get("client"):
        stmt = stmt.where(
            Order.client_name.ilike(f"%{_escape_ilike_wildcards(filters['client'])}%")
        )
    if filters.get("amount_min") is not None:
        stmt = stmt.where(Order.total_amount >= filters["amount_min"])
    if filters.get("amount_max") is not None:
        stmt = stmt.where(Order.total_amount <= filters["amount_max"])
    if filters.get("has_order") is True:
        stmt = stmt.where(Order.related_budget_id.is_not(None))
    elif filters.get("has_order") is False:
        stmt = stmt.where(Order.related_budget_id.is_(None))
    if filters.get("invoiced") is True:
        invoiced_ids = select(Invoice.related_order_id).where(Invoice.related_order_id.is_not(None))
        stmt = stmt.where(Order.id.in_(invoiced_ids))
    elif filters.get("invoiced") is False:
        invoiced_ids = select(Invoice.related_order_id).where(Invoice.related_order_id.is_not(None))
        stmt = stmt.where(Order.id.not_in(invoiced_ids))

    orders = list(db.scalars(stmt).all())
    if access_scope is not None:
        orders = filter_records_by_document_scope(db, orders, access_scope)

    if kind == "count":
        return [
            {"metric": "count", "value": len(orders), "label": "pedidos que cumplen los filtros"}
        ]
    if kind == "total":
        total = sum((o.total_amount or 0.0) for o in orders if o.total_amount is not None)
        return [
            {
                "metric": "total_amount",
                "value": round(total, 2),
                "label": "suma de importes de pedidos",
                "count": len(orders),
            }
        ]
    if kind == "top":
        sorted_os = sorted(orders, key=lambda o: o.total_amount or 0, reverse=True)[:10]
        return [
            {
                "metric": "top_pedido",
                "value": o.total_amount,
                "label": (
                    f"Pedido {o.order_number or o.id} - proveedor {o.supplier_name or '-'} - "
                    f"cliente {o.client_name or '-'} - {o.total_amount or 0:.2f} {o.currency or ''}"
                ).strip(),
                "document_id": o.document_id,
            }
            for o in sorted_os
        ]
    if kind == "by_supplier":
        groups: dict[str, dict[str, Any]] = {}
        for o in orders:
            key = o.supplier_name or "(sin proveedor)"
            g = groups.setdefault(key, {"label": key, "count": 0, "total": 0.0})
            g["count"] += 1
            if o.total_amount is not None:
                g["total"] += o.total_amount
        return [
            {
                "metric": "by_supplier",
                "value": round(g["total"], 2),
                "count": g["count"],
                "label": g["label"],
            }
            for g in sorted(groups.values(), key=lambda x: x["total"], reverse=True)[:10]
        ]
    return []


def _invoice_aggregate(
    db: Session,
    kind: str,
    filters: dict[str, Any],
    access_scope: AccessScope | None = None,
) -> list[dict[str, Any]]:
    stmt = select(Invoice)
    if filters.get("supplier"):
        stmt = stmt.where(
            Invoice.supplier_name.ilike(f"%{_escape_ilike_wildcards(filters['supplier'])}%")
        )
    if filters.get("client"):
        stmt = stmt.where(
            Invoice.client_name.ilike(f"%{_escape_ilike_wildcards(filters['client'])}%")
        )
    if filters.get("amount_min") is not None:
        stmt = stmt.where(Invoice.total_amount >= filters["amount_min"])
    if filters.get("amount_max") is not None:
        stmt = stmt.where(Invoice.total_amount <= filters["amount_max"])
    invoices = list(db.scalars(stmt).all())
    if access_scope is not None:
        invoices = filter_records_by_document_scope(db, invoices, access_scope)
    if kind == "count":
        return [
            {"metric": "count", "value": len(invoices), "label": "facturas que cumplen los filtros"}
        ]
    if kind == "total":
        total = sum((i.total_amount or 0.0) for i in invoices if i.total_amount is not None)
        return [
            {
                "metric": "total_amount",
                "value": round(total, 2),
                "label": "suma de importes facturados",
                "count": len(invoices),
            }
        ]
    return []


def _filters_for_price_scope(
    filters: dict[str, Any], access_scope: AccessScope | None
) -> tuple[dict[str, Any], bool]:
    if access_scope is None or access_scope.can_view_prices:
        return filters, False
    clean = dict(filters)
    redacted = False
    for key in ("amount_min", "amount_max"):
        if key in clean:
            clean.pop(key, None)
            redacted = True
    return clean, redacted


def aggregate_business(
    db: Session,
    *,
    entity: str,
    kind: str,
    query: str | None = None,
    access_scope: AccessScope | None = None,
) -> dict[str, Any]:
    """Run an aggregate query against the structured business tables. Used
    by the agent to answer questions like "cuanto nos hemos gastado en X",
    "cuantos pedidos sin factura hay" or "cual es el proveedor top por
    importe". Returns a list of result rows plus the parsed filters so the
    LLM can show its work."""
    filters, price_redacted = _filters_for_price_scope(
        _money_filters(query if query else entity, query or entity),
        access_scope,
    )
    if (
        access_scope is not None
        and not access_scope.can_view_prices
        and kind.lower() in PRICE_AGGREGATE_KINDS
    ):
        return {
            "entity": entity,
            "kind": kind,
            "rows": [],
            "filters": filters,
            "price_redacted": True,
            "warning": "Los importes estan ocultos por la politica de acceso del usuario.",
        }
    runner = {
        "budget": _budget_aggregate,
        "order": _order_aggregate,
        "invoice": _invoice_aggregate,
    }.get(entity.lower())
    if runner is None:
        return {
            "entity": entity,
            "kind": kind,
            "rows": [],
            "filters": filters,
            "error": f"Tipo de entidad no soportado: {entity}",
        }
    rows = runner(db, kind, filters, access_scope)
    return {
        "entity": entity,
        "kind": kind,
        "rows": rows,
        "filters": filters,
        "price_redacted": price_redacted,
    }
