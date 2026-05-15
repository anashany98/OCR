"""tenant access, hotel scope and folder rules

Revision ID: 0004_tenant_access
Revises: 0003_integration_clients
Create Date: 2026-05-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_tenant_access"
down_revision = "0003_integration_clients"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hotel_chains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hotel_chains_name", "hotel_chains", ["name"], unique=True)
    op.create_index("ix_hotel_chains_is_active", "hotel_chains", ["is_active"])

    op.create_table(
        "hotels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chain_id", sa.Integer(), sa.ForeignKey("hotel_chains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=80)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hotels_chain_id", "hotels", ["chain_id"])
    op.create_index("ix_hotels_name", "hotels", ["name"])
    op.create_index("ix_hotels_code", "hotels", ["code"])
    op.create_index("ix_hotels_is_active", "hotels", ["is_active"])

    op.create_table(
        "document_access_metadata",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chain_id", sa.Integer(), sa.ForeignKey("hotel_chains.id", ondelete="SET NULL")),
        sa.Column("hotel_id", sa.Integer(), sa.ForeignKey("hotels.id", ondelete="SET NULL")),
        sa.Column("assignment_status", sa.String(length=50), nullable=False),
        sa.Column("assignment_source", sa.String(length=80), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("locked_manual", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_access_metadata_document_id", "document_access_metadata", ["document_id"], unique=True)
    op.create_index("ix_document_access_metadata_chain_id", "document_access_metadata", ["chain_id"])
    op.create_index("ix_document_access_metadata_hotel_id", "document_access_metadata", ["hotel_id"])
    op.create_index("ix_document_access_metadata_assignment_status", "document_access_metadata", ["assignment_status"])

    op.create_table(
        "folder_assignment_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255)),
        sa.Column("pattern", sa.String(length=2048), nullable=False),
        sa.Column("match_type", sa.String(length=30), nullable=False),
        sa.Column("chain_id", sa.Integer(), sa.ForeignKey("hotel_chains.id", ondelete="SET NULL")),
        sa.Column("hotel_id", sa.Integer(), sa.ForeignKey("hotels.id", ondelete="SET NULL")),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_folder_assignment_rules_pattern", "folder_assignment_rules", ["pattern"])
    op.create_index("ix_folder_assignment_rules_chain_id", "folder_assignment_rules", ["chain_id"])
    op.create_index("ix_folder_assignment_rules_hotel_id", "folder_assignment_rules", ["hotel_id"])
    op.create_index("ix_folder_assignment_rules_is_active", "folder_assignment_rules", ["is_active"])

    op.create_table(
        "access_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("permissions_json", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_access_groups_name", "access_groups", ["name"], unique=True)
    op.create_index("ix_access_groups_is_active", "access_groups", ["is_active"])

    op.create_table(
        "access_group_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("access_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("principal_type", sa.String(length=30), nullable=False),
        sa.Column("principal_id", sa.String(length=180), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_access_group_members_group_id", "access_group_members", ["group_id"])
    op.create_index("ix_access_group_members_principal_type", "access_group_members", ["principal_type"])
    op.create_index("ix_access_group_members_principal_id", "access_group_members", ["principal_id"])

    op.create_table(
        "sensitive_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sensitive_tags_name", "sensitive_tags", ["name"], unique=True)
    op.create_index("ix_sensitive_tags_is_active", "sensitive_tags", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_sensitive_tags_is_active", table_name="sensitive_tags")
    op.drop_index("ix_sensitive_tags_name", table_name="sensitive_tags")
    op.drop_table("sensitive_tags")
    op.drop_index("ix_access_group_members_principal_id", table_name="access_group_members")
    op.drop_index("ix_access_group_members_principal_type", table_name="access_group_members")
    op.drop_index("ix_access_group_members_group_id", table_name="access_group_members")
    op.drop_table("access_group_members")
    op.drop_index("ix_access_groups_is_active", table_name="access_groups")
    op.drop_index("ix_access_groups_name", table_name="access_groups")
    op.drop_table("access_groups")
    op.drop_index("ix_folder_assignment_rules_is_active", table_name="folder_assignment_rules")
    op.drop_index("ix_folder_assignment_rules_hotel_id", table_name="folder_assignment_rules")
    op.drop_index("ix_folder_assignment_rules_chain_id", table_name="folder_assignment_rules")
    op.drop_index("ix_folder_assignment_rules_pattern", table_name="folder_assignment_rules")
    op.drop_table("folder_assignment_rules")
    op.drop_index("ix_document_access_metadata_assignment_status", table_name="document_access_metadata")
    op.drop_index("ix_document_access_metadata_hotel_id", table_name="document_access_metadata")
    op.drop_index("ix_document_access_metadata_chain_id", table_name="document_access_metadata")
    op.drop_index("ix_document_access_metadata_document_id", table_name="document_access_metadata")
    op.drop_table("document_access_metadata")
    op.drop_index("ix_hotels_is_active", table_name="hotels")
    op.drop_index("ix_hotels_code", table_name="hotels")
    op.drop_index("ix_hotels_name", table_name="hotels")
    op.drop_index("ix_hotels_chain_id", table_name="hotels")
    op.drop_table("hotels")
    op.drop_index("ix_hotel_chains_is_active", table_name="hotel_chains")
    op.drop_index("ix_hotel_chains_name", table_name="hotel_chains")
    op.drop_table("hotel_chains")
