"""professional workflows

Revision ID: 0010_professional_workflows
Revises: 0009_quality_status
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_professional_workflows"
down_revision = "0009_quality_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("priority", sa.String(length=30), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="open"),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("document_pages.id", ondelete="SET NULL")),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("extraction_jobs.id", ondelete="SET NULL")),
        sa.Column("assignee_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_notes", sa.Text()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_work_items_kind", "work_items", ["kind"])
    op.create_index("ix_work_items_status", "work_items", ["status"])
    op.create_index("ix_work_items_priority", "work_items", ["priority"])

    op.create_table(
        "work_item_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_item_id", sa.Integer(), sa.ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_work_item_comments_work_item_id", "work_item_comments", ["work_item_id"])

    op.create_table(
        "document_timeline_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("details_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_timeline_events_document_id", "document_timeline_events", ["document_id"])
    op.create_index("ix_document_timeline_events_event_type", "document_timeline_events", ["event_type"])

    op.create_table(
        "ocr_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("document_pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("corrected_text", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ocr_revisions_page_id", "ocr_revisions", ["page_id"])
    op.create_index("ix_ocr_revisions_document_id", "ocr_revisions", ["document_id"])

    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invoice_number", sa.String(length=120)),
        sa.Column("supplier_name", sa.String(length=255)),
        sa.Column("client_name", sa.String(length=255)),
        sa.Column("date", sa.Date()),
        sa.Column("total_amount", sa.Float()),
        sa.Column("currency", sa.String(length=12)),
        sa.Column("related_order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL")),
        sa.Column("confidence", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_invoices_invoice_number", "invoices", ["invoice_number"])
    op.create_index("ix_invoices_related_order_id", "invoices", ["related_order_id"])

    op.create_table(
        "reconciliation_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("budget_id", sa.Integer(), sa.ForeignKey("budgets.id", ondelete="SET NULL")),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL")),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id", ondelete="SET NULL")),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("expected_amount", sa.Float()),
        sa.Column("actual_amount", sa.Float()),
        sa.Column("resolution_notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "budget_id", "order_id", "invoice_id", name="uq_reconciliation_issue_identity"),
    )
    op.create_index("ix_reconciliation_issues_kind", "reconciliation_issues", ["kind"])
    op.create_index("ix_reconciliation_issues_status", "reconciliation_issues", ["status"])

    op.create_table(
        "saved_views",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("scope", sa.String(length=80), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("is_shared", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "saved_searches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=40), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "notification_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("target", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_notification_rules_event_type", "notification_rules", ["event_type"])
    op.create_index("ix_notification_rules_is_active", "notification_rules", ["is_active"])

    op.create_table(
        "plan_measurements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(length=180), nullable=False),
        sa.Column("page_number", sa.Integer()),
        sa.Column("measurement_type", sa.String(length=50), nullable=False),
        sa.Column("value_m", sa.Float()),
        sa.Column("ocr_value_m", sa.Float()),
        sa.Column("points_json", sa.JSON(), nullable=False),
        sa.Column("calibration_json", sa.JSON()),
        sa.Column("has_discrepancy", sa.Boolean(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_plan_measurements_plan_id", "plan_measurements", ["plan_id"])
    op.create_index("ix_plan_measurements_has_discrepancy", "plan_measurements", ["has_discrepancy"])


def downgrade() -> None:
    for table in [
        "plan_measurements",
        "notification_rules",
        "saved_searches",
        "saved_views",
        "reconciliation_issues",
        "invoices",
        "ocr_revisions",
        "document_timeline_events",
        "work_item_comments",
        "work_items",
    ]:
        op.drop_table(table)
