"""add classification suggestions and learned patterns tables

Revision ID: 0013_learning_loop
Revises: 0012_extraction_job_indexes
Create Date: 2026-06-02
"""

from alembic import op
import sqlalchemy as sa

revision = "0013_learning_loop"
down_revision = "0012_extraction_job_indexes"
branch_labels = None
depends_on = None


def _index_exists(table_name: str, index_name: str, columns: list[str]) -> bool:
    indexes = sa.inspect(op.get_bind()).get_indexes(table_name)
    expected_columns = tuple(columns)
    return any(
        index["name"] == index_name or tuple(index.get("column_names") or ()) == expected_columns
        for index in indexes
    )


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _index_exists(table_name, index_name, columns):
        op.create_index(index_name, table_name, columns)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    indexes = sa.inspect(op.get_bind()).get_indexes(table_name)
    if any(index["name"] == index_name for index in indexes):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    op.create_table(
        "classification_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("integration_client_id", sa.Integer(), nullable=True),
        sa.Column("suggestion_type", sa.String(length=50), nullable=False),
        sa.Column("suggested_document_type", sa.String(length=50), nullable=True),
        sa.Column("current_document_type", sa.String(length=50), nullable=True),
        sa.Column("target_document_id", sa.Integer(), nullable=True),
        sa.Column("pattern_value", sa.Text(), nullable=True),
        sa.Column("target_action", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["integration_client_id"], ["integration_clients.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_table(
        "learned_patterns",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("pattern_type", sa.String(length=50), nullable=False),
        sa.Column("pattern_value", sa.Text(), nullable=False),
        sa.Column("target_class", sa.String(length=50), nullable=True),
        sa.Column("target_action", sa.String(length=50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("source_suggestion_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("applied_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["source_suggestion_id"], ["classification_suggestions.id"], ondelete="SET NULL"),
    )

    _create_index_if_missing("ix_classification_suggestions_status", "classification_suggestions", ["status"])
    _create_index_if_missing("ix_classification_suggestions_document_id", "classification_suggestions", ["document_id"])
    _create_index_if_missing("ix_classification_suggestions_integration_client_id", "classification_suggestions", ["integration_client_id"])
    _create_index_if_missing("ix_classification_suggestions_suggestion_type", "classification_suggestions", ["suggestion_type"])
    _create_index_if_missing("ix_classification_suggestions_created_at", "classification_suggestions", ["created_at"])

    _create_index_if_missing("ix_learned_patterns_status", "learned_patterns", ["status"])
    _create_index_if_missing("ix_learned_patterns_pattern_type", "learned_patterns", ["pattern_type"])
    _create_index_if_missing("ix_learned_patterns_target_action", "learned_patterns", ["target_action"])
    op.create_index(
        "uq_learned_patterns_value",
        "learned_patterns",
        ["pattern_type", "pattern_value", "target_action"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_learned_patterns_value", table_name="learned_patterns")
    _drop_index_if_exists("ix_learned_patterns_target_action", "learned_patterns")
    _drop_index_if_exists("ix_learned_patterns_pattern_type", "learned_patterns")
    _drop_index_if_exists("ix_learned_patterns_status", "learned_patterns")
    _drop_index_if_exists("ix_classification_suggestions_created_at", "classification_suggestions")
    _drop_index_if_exists("ix_classification_suggestions_suggestion_type", "classification_suggestions")
    _drop_index_if_exists("ix_classification_suggestions_integration_client_id", "classification_suggestions")
    _drop_index_if_exists("ix_classification_suggestions_document_id", "classification_suggestions")
    _drop_index_if_exists("ix_classification_suggestions_status", "classification_suggestions")
    op.drop_table("learned_patterns")
    op.drop_table("classification_suggestions")