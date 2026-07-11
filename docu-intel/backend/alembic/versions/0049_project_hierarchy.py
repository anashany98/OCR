"""0049 — Hierarchical project model and document occurrences (Phase 3).

Creates projects, document_occurrences, and document_budget_links tables
for the brand/hotel/project hierarchy and multi-occurrence document tracking.

Revision ID: 0049_project_hierarchy
Revises: 0048_construction_work_items
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa

revision = "0049_project_hierarchy"
down_revision = "0048_construction_work_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Projects
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("year", sa.Integer, nullable=False, index=True),
        sa.Column("brand_id", sa.Integer, sa.ForeignKey("hotel_chains.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("hotel_id", sa.Integer, sa.ForeignKey("hotels.id", ondelete="SET NULL"), index=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("primary_budget_scope_id", sa.Integer, sa.ForeignKey("budget_scopes.id", ondelete="SET NULL"), index=True),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("manager_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Document occurrences
    op.create_table(
        "document_occurrences",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source_path", sa.Text, nullable=False),
        sa.Column("source_root", sa.Text, nullable=False),
        sa.Column("year", sa.Integer, nullable=False, index=True),
        sa.Column("brand_id", sa.Integer, sa.ForeignKey("hotel_chains.id", ondelete="SET NULL"), nullable=False, index=True),
        sa.Column("hotel_id", sa.Integer, sa.ForeignKey("hotels.id", ondelete="SET NULL"), index=True),
        sa.Column("budget_scope_id", sa.Integer, sa.ForeignKey("budget_scopes.id", ondelete="SET NULL"), index=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="SET NULL"), index=True),
        sa.Column("category", sa.String(100), nullable=False, server_default="otros"),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_occurrence_source", "document_occurrences", ["source_root", "source_path"])

    # Document budget links
    op.create_table(
        "document_budget_links",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("occurrence_id", sa.Integer, sa.ForeignKey("document_occurrences.id", ondelete="SET NULL"), index=True),
        sa.Column("budget_scope_id", sa.Integer, sa.ForeignKey("budget_scopes.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source", sa.String(30), nullable=False, server_default="folder"),
        sa.Column("extracted_code", sa.String(100)),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="verified"),
        sa.Column("evidence_json", sa.JSON),
        sa.Column("reviewed_by_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_doc_budget_link", "document_budget_links", ["document_id", "budget_scope_id"])


def downgrade() -> None:
    op.drop_table("document_budget_links")
    op.drop_table("document_occurrences")
    op.drop_table("projects")
