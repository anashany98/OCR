"""Phase 7 — Communication models for email threads, messages, and participants.

Converts .msg files into consultable conversations without losing the
original document. Models cover threads, messages, participants,
attachments, and project-level communication tracking.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Organization(Base):
    """An external organization (client, supplier, etc.)."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    domain: Mapped[str | None] = mapped_column(String(200), index=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class Contact(Base):
    """A person who appears in emails or project communications."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"),
        index=True,
    )
    phone: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    organization = relationship("Organization")


class CommunicationThread(Base):
    """An email thread (conversation) with one or more messages."""

    __tablename__ = "communication_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        index=True,
    )
    budget_scope_id: Mapped[int | None] = mapped_column(
        ForeignKey("budget_scopes.id", ondelete="SET NULL"),
        index=True,
    )
    message_id_header: Mapped[str | None] = mapped_column(String(500), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    messages = relationship(
        "CommunicationMessage", back_populates="thread", cascade="all, delete-orphan"
    )
    participants = relationship(
        "CommunicationParticipant", back_populates="thread", cascade="all, delete-orphan"
    )


class CommunicationMessage(Base):
    """A single email/message within a thread."""

    __tablename__ = "communication_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("communication_threads.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
    )
    message_id_header: Mapped[str | None] = mapped_column(String(500), index=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(500))
    from_email: Mapped[str] = mapped_column(String(320), nullable=False)
    from_name: Mapped[str | None] = mapped_column(String(300))
    to_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    cc_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    thread = relationship("CommunicationThread", back_populates="messages")
    attachments = relationship(
        "AttachmentLink", back_populates="message", cascade="all, delete-orphan"
    )


class CommunicationParticipant(Base):
    """Links a contact to a thread with a role."""

    __tablename__ = "communication_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("communication_threads.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"),
        index=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(
        String(30),
        default="unknown",
        nullable=False,
    )  # from | to | cc | bcc
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    thread = relationship("CommunicationThread", back_populates="participants")
    contact = relationship("Contact")


class AttachmentLink(Base):
    """Links an attachment (document) to a message."""

    __tablename__ = "attachment_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("communication_messages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    message = relationship("CommunicationMessage", back_populates="attachments")
    document = relationship("Document")


class ProjectParticipant(Base):
    """A person's role in a project (internal or external)."""

    __tablename__ = "project_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"),
        index=True,
    )
    email: Mapped[str | None] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(
        String(30),
        default="unknown",
        nullable=False,
        index=True,
    )  # gestor_interno | comercial_interno | comercial_externo | cliente | proveedor | arquitecto | instalador | tecnico | otro
    role_confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    project = relationship("Project")
    contact = relationship("Contact")


class ProjectEvent(Base):
    """A notable event in a project (decision, commitment, milestone)."""

    __tablename__ = "project_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )  # decision | commitment | milestone | issue | resolution
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
    )
    source_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("communication_messages.id", ondelete="SET NULL"),
        index=True,
    )
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    project = relationship("Project")


class ProjectIssue(Base):
    """A problem or incident tracked in a project."""

    __tablename__ = "project_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20),
        default="medium",
        nullable=False,
        index=True,
    )  # low | medium | high | critical
    status: Mapped[str] = mapped_column(
        String(20),
        default="open",
        nullable=False,
        index=True,
    )  # open | in_progress | resolved | ignored
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
    )
    source_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("communication_messages.id", ondelete="SET NULL"),
        index=True,
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    project = relationship("Project")
