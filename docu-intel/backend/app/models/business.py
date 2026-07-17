from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    budget_number: Mapped[str | None] = mapped_column(String(120), index=True)
    # BE-LOOKUP-1 (Sprint 2): pre-normalized form for O(1) fuzzy
    # lookup. Populated on INSERT/UPDATE so the related-order
    # resolution can do a single indexed SELECT instead of
    # loading 500 rows into Python. The normalization strips
    # whitespace, hyphens, dots, slashes and lower-cases.
    budget_number_normalized: Mapped[str | None] = mapped_column(
        String(120), index=True, nullable=True
    )
    client_name: Mapped[str | None] = mapped_column(String(255), index=True)
    # Partial scans can lack a date. Persist the recoverable facts and send
    # the document to review instead of failing the entire extraction.
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(12))
    status: Mapped[str | None] = mapped_column(String(50), index=True)
    accepted_detected: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    lines = relationship("BudgetLine", back_populates="budget", cascade="all, delete-orphan")


class BudgetLine(Base):
    __tablename__ = "budget_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    budget_id: Mapped[int] = mapped_column(
        ForeignKey("budgets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reference: Mapped[str | None] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(50))
    unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    total_price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    confidence: Mapped[float | None] = mapped_column(Float)

    budget = relationship("Budget", back_populates="lines")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    order_number: Mapped[str | None] = mapped_column(String(120), index=True)
    # BE-LOOKUP-1 (Sprint 2): pre-normalized form for O(1) fuzzy
    # lookup. Same normalization as Budget.budget_number_normalized.
    order_number_normalized: Mapped[str | None] = mapped_column(
        String(120), index=True, nullable=True
    )
    supplier_name: Mapped[str | None] = mapped_column(String(255), index=True)
    client_name: Mapped[str | None] = mapped_column(String(255), index=True)
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(12))
    related_budget_id: Mapped[int | None] = mapped_column(
        ForeignKey("budgets.id", ondelete="SET NULL"), index=True
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    lines = relationship("OrderLine", back_populates="order", cascade="all, delete-orphan")


class OrderLine(Base):
    __tablename__ = "order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reference: Mapped[str | None] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(50))
    unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    total_price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    confidence: Mapped[float | None] = mapped_column(Float)

    order = relationship("Order", back_populates="lines")


class DeliveryNote(Base):
    __tablename__ = "delivery_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    delivery_number: Mapped[str | None] = mapped_column(String(120), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(255), index=True)
    client_name: Mapped[str | None] = mapped_column(String(255), index=True)
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(12))
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    lines = relationship(
        "DeliveryNoteLine", back_populates="delivery_note", cascade="all, delete-orphan"
    )


class DeliveryNoteLine(Base):
    __tablename__ = "delivery_note_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_note_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_notes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reference: Mapped[str | None] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(50))
    unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    total_price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    confidence: Mapped[float | None] = mapped_column(Float)

    delivery_note = relationship("DeliveryNote", back_populates="lines")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_name: Mapped[str | None] = mapped_column(String(255), index=True)
    scale_text: Mapped[str | None] = mapped_column(String(80))
    scale_ratio: Mapped[float | None] = mapped_column(Float)
    scale_confidence: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(20))
    has_valid_scale: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    # P5 — multi-sheet association. ``project_phase`` groups
    # plans that belong to the same building phase (e.g.
    # "PLANTA PRIMERA", "SECCIÓN A-A", "ALZADO NORTE").
    # ``revision`` tracks the drawing revision (e.g. "A", "B",
    # "REV01"). Both fields are detected from the plan text via
    # :func:`app.services.plan_extraction.extract_plan_phase`.
    project_phase: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    revision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cad_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cad_extents_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    cad_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    coordinate_transform_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    conversion_provenance_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    rooms = relationship("PlanRoom", back_populates="plan", cascade="all, delete-orphan")
    dimensions = relationship("PlanDimension", back_populates="plan", cascade="all, delete-orphan")
    symbols = relationship("PlanSymbol", back_populates="plan", cascade="all, delete-orphan")
    cad_entities = relationship(
        "PlanCadEntity", back_populates="plan", cascade="all, delete-orphan"
    )


class PlanRoom(Base):
    __tablename__ = "plan_rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), index=True, nullable=False
    )
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
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), index=True, nullable=False
    )
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
    source_method: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    source_entity_handle: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    layer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    native_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    native_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unit_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    coordinates_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(30), nullable=False, default="auto")
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    plan = relationship("Plan", back_populates="dimensions")


class PlanCadEntity(Base):
    """Native CAD entity retained for grounding and visual overlays."""

    __tablename__ = "plan_cad_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), index=True, nullable=False
    )
    entity_handle: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    layer: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    layout: Mapped[str | None] = mapped_column(String(120), nullable=True)
    geometry_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    properties_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source_method: Mapped[str] = mapped_column(String(40), nullable=False, default="cad_dxf")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(30), nullable=False, default="auto")

    plan = relationship("Plan", back_populates="cad_entities")


class PlanSymbol(Base):
    """P2 — A single symbol detected in a plan by the YOLO detector.

    One row per detection, so a plan with 12 outlets + 4 windows has
    16 rows. The bounding box is stored in PDF coordinates (points)
    to match :class:`PlanDimension` and the rest of the plan geometry.
    """

    __tablename__ = "plan_symbols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), index=True, nullable=False
    )
    symbol_class: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_x1: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_y1: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_x2: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_y2: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    plan = relationship("Plan", back_populates="symbols")


class InvoiceLine(Base):
    """A single line item from an invoice extraction (Phase 6)."""

    __tablename__ = "invoice_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    reference: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(20))
    unit_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    total_price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(12))
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    invoice = relationship("Invoice", back_populates="lines")
