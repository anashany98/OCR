from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class IntegrationClient(Base):
    __tablename__ = "integration_clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccessPolicy(Base):
    __tablename__ = "access_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    permissions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    technician_profiles = relationship("TechnicianAccessProfile", back_populates="access_policy")


class TechnicianAccessProfile(Base):
    __tablename__ = "technician_access_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    technician_id: Mapped[str] = mapped_column(String(180), unique=True, index=True, nullable=False)
    technician_name: Mapped[str | None] = mapped_column(String(255))
    access_policy_id: Mapped[int] = mapped_column(ForeignKey("access_policies.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    access_policy = relationship("AccessPolicy", back_populates="technician_profiles")
