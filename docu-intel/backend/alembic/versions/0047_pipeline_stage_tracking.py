"""0047 — Add pipeline stage tracking fields to documents.

P0.3: adds fields that let the API report processing progress
per-stage without breaking existing consumers. The ``status`` column
is preserved for backward compatibility; ``pipeline_stage`` is the
granular internal state.

Revision ID: 0047_pipeline_stage_tracking
Revises: 0046_migrate_financial_to_numeric
Create Date: 2026-07-10
"""

from alembic import op
import sqlalchemy as sa

revision = "0047_pipeline_stage_tracking"
down_revision = "0046_migrate_financial_to_numeric"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "pipeline_stage",
            sa.String(40),
            nullable=True,
            comment="Current pipeline stage: probing|text_processing|text_ready|metadata_ready|embedding_pending|searchable|fully_processed|needs_review|failed",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "pages_completed",
            sa.Integer(),
            nullable=True,
            comment="Pages processed so far",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "pages_total",
            sa.Integer(),
            nullable=True,
            comment="Total pages in document",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "text_search_ready",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Text available for lexical search",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "semantic_search_ready",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Embeddings available for semantic search",
        ),
    )
    op.create_index(
        "ix_documents_pipeline_stage",
        "documents",
        ["pipeline_stage"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_documents_pipeline_stage", table_name="documents")
    op.drop_column("documents", "semantic_search_ready")
    op.drop_column("documents", "text_search_ready")
    op.drop_column("documents", "pages_total")
    op.drop_column("documents", "pages_completed")
    op.drop_column("documents", "pipeline_stage")
