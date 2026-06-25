from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class HotelChain(Base):
    __tablename__ = "hotel_chains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    hotels = relationship("Hotel", back_populates="chain", cascade="all, delete-orphan")


class Hotel(Base):
    __tablename__ = "hotels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chain_id: Mapped[int] = mapped_column(
        ForeignKey("hotel_chains.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    code: Mapped[str | None] = mapped_column(String(80), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    chain = relationship("HotelChain", back_populates="hotels")


class DocumentAccessMetadata(Base):
    __tablename__ = "document_access_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True, index=True
    )
    chain_id: Mapped[int | None] = mapped_column(
        ForeignKey("hotel_chains.id", ondelete="SET NULL"), index=True
    )
    hotel_id: Mapped[int | None] = mapped_column(
        ForeignKey("hotels.id", ondelete="SET NULL"), index=True
    )
    assignment_status: Mapped[str] = mapped_column(
        String(50), default="quarantine", nullable=False, index=True
    )
    assignment_source: Mapped[str] = mapped_column(String(80), default="none", nullable=False)
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    locked_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    document = relationship("Document", back_populates="access_metadata")
    chain = relationship("HotelChain")
    hotel = relationship("Hotel")


class FolderAssignmentRule(Base):
    __tablename__ = "folder_assignment_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    pattern: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    match_type: Mapped[str] = mapped_column(String(30), default="contains", nullable=False)
    chain_id: Mapped[int | None] = mapped_column(
        ForeignKey("hotel_chains.id", ondelete="SET NULL"), index=True
    )
    hotel_id: Mapped[int | None] = mapped_column(
        ForeignKey("hotels.id", ondelete="SET NULL"), index=True
    )
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    chain = relationship("HotelChain")
    hotel = relationship("Hotel")


class AccessGroup(Base):
    __tablename__ = "access_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    permissions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    members = relationship(
        "AccessGroupMember", back_populates="group", cascade="all, delete-orphan"
    )


class AccessGroupMember(Base):
    __tablename__ = "access_group_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("access_groups.id", ondelete="CASCADE"), index=True, nullable=False
    )
    principal_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    principal_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    group = relationship("AccessGroup", back_populates="members")


class SensitiveTag(Base):
    __tablename__ = "sensitive_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
