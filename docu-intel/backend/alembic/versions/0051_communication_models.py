"""0051 — Communication models (Phase 7).

Creates organizations, contacts, communication_threads, communication_messages,
communication_participants, attachment_links, project_participants,
project_events, and project_issues tables.

Revision ID: 0051_communication_models
Revises: 0050_invoice_lines
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa

revision = "0051_communication_models"
down_revision = "0050_invoice_lines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Organizations
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(300), nullable=False, index=True),
        sa.Column("domain", sa.String(200), index=True),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Contacts
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("email", sa.String(320), nullable=False, index=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="SET NULL"), index=True),
        sa.Column("phone", sa.String(50)),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Communication threads
    op.create_table(
        "communication_threads",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subject", sa.String(500), nullable=False, index=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="SET NULL"), index=True),
        sa.Column("budget_scope_id", sa.Integer, sa.ForeignKey("budget_scopes.id", ondelete="SET NULL"), index=True),
        sa.Column("message_id_header", sa.String(500), index=True),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("message_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Communication messages
    op.create_table(
        "communication_messages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("thread_id", sa.Integer, sa.ForeignKey("communication_threads.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="SET NULL"), index=True),
        sa.Column("message_id_header", sa.String(500), index=True),
        sa.Column("in_reply_to", sa.String(500)),
        sa.Column("from_email", sa.String(320), nullable=False),
        sa.Column("from_name", sa.String(300)),
        sa.Column("to_json", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("cc_json", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body_text", sa.Text, nullable=False, server_default=""),
        sa.Column("body_html", sa.Text),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("has_attachments", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Communication participants
    op.create_table(
        "communication_participants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("thread_id", sa.Integer, sa.ForeignKey("communication_threads.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id", ondelete="SET NULL"), index=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(30), nullable=False, server_default="unknown"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Attachment links
    op.create_table(
        "attachment_links",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("message_id", sa.Integer, sa.ForeignKey("communication_messages.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Project participants
    op.create_table(
        "project_participants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id", ondelete="SET NULL"), index=True),
        sa.Column("email", sa.String(320)),
        sa.Column("role", sa.String(30), nullable=False, server_default="unknown", index=True),
        sa.Column("role_confidence", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Project events
    op.create_table(
        "project_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("event_type", sa.String(50), nullable=False, index=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("source_document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="SET NULL"), index=True),
        sa.Column("source_message_id", sa.Integer, sa.ForeignKey("communication_messages.id", ondelete="SET NULL"), index=True),
        sa.Column("event_date", sa.DateTime(timezone=True)),
        sa.Column("details_json", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Project issues
    op.create_table(
        "project_issues",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("severity", sa.String(20), nullable=False, server_default="medium", index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open", index=True),
        sa.Column("source_document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="SET NULL"), index=True),
        sa.Column("source_message_id", sa.Integer, sa.ForeignKey("communication_messages.id", ondelete="SET NULL"), index=True),
        sa.Column("resolution_notes", sa.Text),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("project_issues")
    op.drop_table("project_events")
    op.drop_table("project_participants")
    op.drop_table("attachment_links")
    op.drop_table("communication_participants")
    op.drop_table("communication_messages")
    op.drop_table("communication_threads")
    op.drop_table("contacts")
    op.drop_table("organizations")
