"""Persist contextual-occurrence association evidence and state.

Revision ID: 0061_contextual_occurrence_provenance
Revises: 0060_minimax_m3_processing_route
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0061_contextual_occurrence_provenance"
down_revision = "0060_minimax_m3_processing_route"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_occurrences", sa.Column("folder_budget_code", sa.String(120)))
    op.add_column("document_occurrences", sa.Column("document_budget_code", sa.String(120)))
    op.add_column("document_occurrences", sa.Column("resolved_budget_code", sa.String(120)))
    op.add_column(
        "document_occurrences",
        sa.Column(
            "association_status",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'folder_only'"),
        ),
    )
    op.add_column("document_occurrences", sa.Column("association_evidence", sa.JSON()))
    op.create_index(
        "ix_document_occurrences_folder_budget_code",
        "document_occurrences",
        ["folder_budget_code"],
    )
    op.create_index(
        "ix_document_occurrences_document_budget_code",
        "document_occurrences",
        ["document_budget_code"],
    )
    op.create_index(
        "ix_document_occurrences_resolved_budget_code",
        "document_occurrences",
        ["resolved_budget_code"],
    )
    op.create_index(
        "ix_document_occurrences_association_status",
        "document_occurrences",
        ["association_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_occurrences_association_status", table_name="document_occurrences")
    op.drop_index("ix_document_occurrences_resolved_budget_code", table_name="document_occurrences")
    op.drop_index("ix_document_occurrences_document_budget_code", table_name="document_occurrences")
    op.drop_index("ix_document_occurrences_folder_budget_code", table_name="document_occurrences")
    op.drop_column("document_occurrences", "association_evidence")
    op.drop_column("document_occurrences", "association_status")
    op.drop_column("document_occurrences", "resolved_budget_code")
    op.drop_column("document_occurrences", "document_budget_code")
    op.drop_column("document_occurrences", "folder_budget_code")
