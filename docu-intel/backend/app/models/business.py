from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    budget_number: Mapped[str | None] = mapped_column(String(120), index=True)
    client_name: Mapped[str | None] = mapped_column(String(255), index=True)
    date: Mapped[date | None] = mapped_column(Date)
    total_amount: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(12))
    status: Mapped[str | None] = mapped_column(String(50), index=True)
    accepted_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    lines = relationship("BudgetLine", back_populates="budget", cascade="all, delete-orphan")


class BudgetLine(Base):
    __tablename__ = "budget_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budgets.id", ondelete="CASCADE"), index=True, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(50))
    unit_price: Mapped[float | None] = mapped_column(Float)
    total_price: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)

    budget = relationship("Budget", back_populates="lines")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    order_number: Mapped[str | None] = mapped_column(String(120), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(255), index=True)
    client_name: Mapped[str | None] = mapped_column(String(255), index=True)
    date: Mapped[date | None] = mapped_column(Date)
    total_amount: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(12))
    related_budget_id: Mapped[int | None] = mapped_column(ForeignKey("budgets.id", ondelete="SET NULL"), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    lines = relationship("OrderLine", back_populates="order", cascade="all, delete-orphan")


class OrderLine(Base):
    __tablename__ = "order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(50))
    unit_price: Mapped[float | None] = mapped_column(Float)
    total_price: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)

    order = relationship("Order", back_populates="lines")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    project_name: Mapped[str | None] = mapped_column(String(255), index=True)
    scale_text: Mapped[str | None] = mapped_column(String(80))
    scale_ratio: Mapped[float | None] = mapped_column(Float)
    scale_confidence: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(20))
    has_valid_scale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    # P5 — multi-sheet association. ``project_phase`` groups
    # plans that belong to the same building phase (e.g.
    # "PLANTA PRIMERA", "SECCIÓN A-A", "ALZADO NORTE").
    # ``revision`` tracks the drawing revision (e.g. "A", "B",
    # "REV01"). Both fields are detected from the plan text via
    # :func:`app.services.plan_extraction.extract_plan_phase`.
    project_phase: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    revision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    rooms = relationship("PlanRoom", back_populates="plan", cascade="all, delete-orphan")
    dimensions = relationship("PlanDimension", back_populates="plan", cascade="all, delete-orphan")
    symbols = relationship("PlanSymbol", back_populates="plan", cascade="all, delete-orphan")


class PlanRoom(Base):
    __tablename__ = "plan_rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(180), index=True)
    area_m2: Mapped[float | None] = mapped_column(Float)
    width_m: Mapped[float | None] = mapped_column(Float)
    length_m: Mapped[float | None] = mapped_column(Float)
    polygon_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    confidence: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String(80))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    plan = relationship("Plan", back_populates="rooms")


class PlanDimension(Base):
    __tablename__ = "plan_dimensions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(20))
    value_m: Mapped[float | None] = mapped_column(Float)
    page_number: Mapped[int | None] = mapped_column(Integer)
    bbox_x1: Mapped[float | None] = mapped_column(Float)
    bbox_y1: Mapped[float | None] = mapped_column(Float)
    bbox_x2: Mapped[float | None] = mapped_column(Float)
    bbox_y2: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)

    plan = relationship("Plan", back_populates="dimensions")


class PlanSymbol(Base):
    """P2 — A single symbol detected in a plan by the YOLO detector.

    One row per detection, so a plan with 12 outlets + 4 windows has
    16 rows. The bounding box is stored in PDF coordinates (points)
    to match :class:`PlanDimension` and the rest of the plan geometry.
    """

    __tablename__ = "plan_symbols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True, nullable=False)
    symbol_class: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_x1: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_y1: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_x2: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_y2: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    plan = relationship("Plan", back_populates="symbols")

