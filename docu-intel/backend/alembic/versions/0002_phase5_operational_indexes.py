"""phase5 operational indexes

Revision ID: 0002_phase5_operational_indexes
Revises: 0001_initial_schema
Create Date: 2026-05-13
"""

from alembic import op

revision = "0002_phase5_operational_indexes"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_documents_status_type_created", "documents", ["status", "document_type", "created_at"])
    op.create_index("ix_documents_deleted_created", "documents", ["deleted_at", "created_at"])
    op.create_index("ix_extraction_jobs_status_id", "extraction_jobs", ["status", "id"])
    op.create_index("ix_extraction_jobs_document_status", "extraction_jobs", ["document_id", "status"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_action_created", "audit_logs", ["action", "created_at"])
    op.create_index("ix_budgets_accepted_status", "budgets", ["accepted_detected", "status"])
    op.create_index("ix_orders_related_created", "orders", ["related_budget_id", "created_at"])
    op.create_index("ix_plans_scale_created", "plans", ["has_valid_scale", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_plans_scale_created", table_name="plans")
    op.drop_index("ix_orders_related_created", table_name="orders")
    op.drop_index("ix_budgets_accepted_status", table_name="budgets")
    op.drop_index("ix_audit_logs_action_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_extraction_jobs_document_status", table_name="extraction_jobs")
    op.drop_index("ix_extraction_jobs_status_id", table_name="extraction_jobs")
    op.drop_index("ix_documents_deleted_created", table_name="documents")
    op.drop_index("ix_documents_status_type_created", table_name="documents")
