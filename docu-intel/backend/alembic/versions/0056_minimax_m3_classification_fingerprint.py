"""MiniMax M3 — multi-dimensional classification and extraction fingerprint.

Revision ID: 0056_minimax_m3_classification_fingerprint
Revises: 0055_fix_partitioned_job_references

Adds the FASE 2 / FASE 3 columns:

* ``source_format``         — physical file format (email, spreadsheet,
                              word, pdf, image, dxf, unknown).
* ``document_subtype``      — variant of the business type
                              (firmado, aceptado, proveedor, ...).
* ``content_tags``          — JSON list of descriptive tags
                              (carpinteria, plano, fotografias, ...).
* ``classification_evidence`` — JSON object explaining the winning
                              signal per dimension.
* ``classifier_version``    — string identifying the ruleset/prompt
                              that produced the labels.
* ``classified_at``         — when the current labels were assigned.
* ``extraction_fingerprint`` — SHA-256 of the text hash + provider +
                              model + prompt version + schema version
                              + extractor version. Identical values
                              skip the provider call (FASE 3).
* ``extraction_fingerprint_at`` — when the fingerprint was last
                              computed. Distinct from ``classified_at``
                              so a re-classification does not need to
                              wipe the extraction cache.

All new columns have safe defaults so existing rows are valid
without a backfill. The corresponding model fields are added in
``app.models.document`` with the same defaults.

The downgrade drops the columns; data is not preserved on
downgrade because the columns are nullable. ``classified_at``,
``extraction_fingerprint_at`` and ``classified_at`` use the existing
``datetime.now(UTC)`` server default so re-classification can rely
on a known timestamp.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0056_minimax_m3_classification_fingerprint"
down_revision = "0055_fix_partitioned_job_references"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("source_format", sa.String(length=40), nullable=True, index=True),
    )
    op.add_column(
        "documents",
        sa.Column("document_subtype", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "content_tags",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "classification_evidence",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.add_column(
        "documents",
        sa.Column("classifier_version", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("extraction_fingerprint", sa.String(length=64), nullable=True, index=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "extraction_fingerprint_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Composite index for the FASE 3 fingerprint short-circuit: when
    # the fingerprint is present and matches the current value, the
    # pipeline can skip the extraction call.
    op.create_index(
        "ix_documents_fingerprint_status",
        "documents",
        ["extraction_fingerprint", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_documents_fingerprint_status", table_name="documents")
    op.drop_column("documents", "extraction_fingerprint_at")
    op.drop_column("documents", "extraction_fingerprint")
    op.drop_column("documents", "classified_at")
    op.drop_column("documents", "classifier_version")
    op.drop_column("documents", "classification_evidence")
    op.drop_column("documents", "content_tags")
    op.drop_column("documents", "document_subtype")
    op.drop_column("documents", "source_format")
