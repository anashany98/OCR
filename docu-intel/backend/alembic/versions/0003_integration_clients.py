"""integration clients and access policies

Revision ID: 0003_integration_clients
Revises: 0002_phase5_operational_indexes
Create Date: 2026-05-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_integration_clients"
down_revision = "0002_phase5_operational_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("api_key_hash", sa.String(length=255), nullable=False),
        sa.Column("scopes_json", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_integration_clients_name", "integration_clients", ["name"], unique=True)
    op.create_index("ix_integration_clients_is_active", "integration_clients", ["is_active"])

    op.create_table(
        "access_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("permissions_json", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_access_policies_name", "access_policies", ["name"], unique=True)
    op.create_index("ix_access_policies_is_default", "access_policies", ["is_default"])

    op.create_table(
        "technician_access_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("technician_id", sa.String(length=180), nullable=False),
        sa.Column("technician_name", sa.String(length=255)),
        sa.Column("access_policy_id", sa.Integer(), sa.ForeignKey("access_policies.id", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_technician_access_profiles_technician_id", "technician_access_profiles", ["technician_id"], unique=True)
    op.create_index("ix_technician_access_profiles_access_policy_id", "technician_access_profiles", ["access_policy_id"])


def downgrade() -> None:
    op.drop_index("ix_technician_access_profiles_access_policy_id", table_name="technician_access_profiles")
    op.drop_index("ix_technician_access_profiles_technician_id", table_name="technician_access_profiles")
    op.drop_table("technician_access_profiles")
    op.drop_index("ix_access_policies_is_default", table_name="access_policies")
    op.drop_index("ix_access_policies_name", table_name="access_policies")
    op.drop_table("access_policies")
    op.drop_index("ix_integration_clients_is_active", table_name="integration_clients")
    op.drop_index("ix_integration_clients_name", table_name="integration_clients")
    op.drop_table("integration_clients")
