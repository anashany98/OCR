"""budget scopes for integration sessions

Revision ID: 0006_budget_scopes
Revises: 0005_operational_hardening
Create Date: 2026-05-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_budget_scopes"
down_revision = "0005_operational_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budget_scopes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("budget_code", sa.String(length=120), nullable=False),
        sa.Column("source_path", sa.Text()),
        sa.Column("local_path", sa.Text()),
        sa.Column("display_name", sa.String(length=255)),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("total_files", sa.Integer(), nullable=False),
        sa.Column("processed_files", sa.Integer(), nullable=False),
        sa.Column("failed_files", sa.Integer(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_processed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_budget_scopes_budget_code", "budget_scopes", ["budget_code"], unique=True)
    op.create_index("ix_budget_scopes_status", "budget_scopes", ["status"])

    op.add_column("documents", sa.Column("budget_scope_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_documents_budget_scope_id_budget_scopes",
        "documents",
        "budget_scopes",
        ["budget_scope_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_documents_budget_scope_id", "documents", ["budget_scope_id"])

    op.create_table(
        "api_client_budget_scopes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("api_client_id", sa.Integer(), sa.ForeignKey("integration_clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("budget_scope_id", sa.Integer(), sa.ForeignKey("budget_scopes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("can_query", sa.Boolean(), nullable=False),
        sa.Column("can_see_amounts", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("api_client_id", "budget_scope_id", name="uq_api_client_budget_scope"),
    )
    op.create_index("ix_api_client_budget_scopes_api_client_id", "api_client_budget_scopes", ["api_client_id"])
    op.create_index("ix_api_client_budget_scopes_budget_scope_id", "api_client_budget_scopes", ["budget_scope_id"])


def downgrade() -> None:
    op.drop_index("ix_api_client_budget_scopes_budget_scope_id", table_name="api_client_budget_scopes")
    op.drop_index("ix_api_client_budget_scopes_api_client_id", table_name="api_client_budget_scopes")
    op.drop_table("api_client_budget_scopes")

    op.drop_index("ix_documents_budget_scope_id", table_name="documents")
    op.drop_constraint("fk_documents_budget_scope_id_budget_scopes", "documents", type_="foreignkey")
    op.drop_column("documents", "budget_scope_id")

    op.drop_index("ix_budget_scopes_status", table_name="budget_scopes")
    op.drop_index("ix_budget_scopes_budget_code", table_name="budget_scopes")
    op.drop_table("budget_scopes")
