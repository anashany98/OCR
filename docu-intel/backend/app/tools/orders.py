"""Order-related tools for the AI agent.

Used to answer questions about orders, suppliers, and related data.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order


def search_orders(db: Session, query: str):
    pattern = f"%{query}%"
    stmt = select(Order).where(
        (Order.order_number.ilike(pattern)) | (Order.supplier_name.ilike(pattern))
    )
    return list(db.scalars(stmt.limit(20)).all())


def get_order_by_number(db: Session, order_number: str):
    return db.scalar(select(Order).where(Order.order_number == order_number).limit(1))
