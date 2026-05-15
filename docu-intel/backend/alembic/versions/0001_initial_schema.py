"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-13
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("stored_filename", sa.String(length=1024)),
        sa.Column("source_path", sa.String(length=2048)),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=255)),
        sa.Column("extension", sa.String(length=32)),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("page_count", sa.Integer()),
        sa.Column("error_message", sa.Text()),
        sa.Column("duplicate_of_document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_documents_file_hash", "documents", ["file_hash"])
    op.create_index("ix_documents_source_path", "documents", ["source_path"])
    op.create_index("ix_documents_document_type", "documents", ["document_type"])
    op.create_index("ix_documents_status", "documents", ["status"])

    op.create_table(
        "document_pages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("width", sa.Float()),
        sa.Column("height", sa.Float()),
        sa.Column("text", sa.Text()),
        sa.Column("image_path", sa.String(length=1024)),
        sa.Column("ocr_confidence", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_pages_document_id", "document_pages", ["document_id"])
    op.create_index("ix_document_pages_page_number", "document_pages", ["page_number"])
    op.execute("CREATE INDEX ix_document_pages_text_trgm ON document_pages USING gin (text gin_trgm_ops)")
    op.execute("CREATE INDEX ix_document_pages_text_fts ON document_pages USING gin (to_tsvector('spanish', coalesce(text, '')))")

    op.create_table(
        "document_blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("document_pages.id", ondelete="CASCADE")),
        sa.Column("page_number", sa.Integer()),
        sa.Column("block_type", sa.String(length=50), nullable=False),
        sa.Column("text", sa.Text()),
        sa.Column("bbox_x1", sa.Float()),
        sa.Column("bbox_y1", sa.Float()),
        sa.Column("bbox_x2", sa.Float()),
        sa.Column("bbox_y2", sa.Float()),
        sa.Column("confidence", sa.Float()),
        sa.Column("source_engine", sa.String(length=80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_blocks_document_id", "document_blocks", ["document_id"])
    op.create_index("ix_document_blocks_page_id", "document_blocks", ["page_id"])
    op.create_index("ix_document_blocks_page_number", "document_blocks", ["page_number"])
    op.execute("CREATE INDEX ix_document_blocks_text_trgm ON document_blocks USING gin (text gin_trgm_ops)")
    op.execute("CREATE INDEX ix_document_blocks_text_fts ON document_blocks USING gin (to_tsvector('spanish', coalesce(text, '')))")

    op.create_table(
        "document_entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text()),
        sa.Column("confidence", sa.Float()),
        sa.Column("page_number", sa.Integer()),
        sa.Column("source_block_id", sa.Integer(), sa.ForeignKey("document_blocks.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_entities_document_id", "document_entities", ["document_id"])
    op.create_index("ix_document_entities_entity_type", "document_entities", ["entity_type"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer()),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024)),
        sa.Column("token_count", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])

    op.create_table(
        "extraction_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.Column("retries", sa.Integer(), nullable=False),
    )
    op.create_index("ix_extraction_jobs_document_id", "extraction_jobs", ["document_id"])
    op.create_index("ix_extraction_jobs_status", "extraction_jobs", ["status"])

    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("budget_number", sa.String(length=120)),
        sa.Column("client_name", sa.String(length=255)),
        sa.Column("date", sa.Date()),
        sa.Column("total_amount", sa.Float()),
        sa.Column("currency", sa.String(length=12)),
        sa.Column("status", sa.String(length=50)),
        sa.Column("accepted_detected", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_budgets_document_id", "budgets", ["document_id"])
    op.create_index("ix_budgets_budget_number", "budgets", ["budget_number"])
    op.create_index("ix_budgets_client_name", "budgets", ["client_name"])
    op.create_index("ix_budgets_status", "budgets", ["status"])

    op.create_table(
        "budget_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("budget_id", sa.Integer(), sa.ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reference", sa.String(length=120)),
        sa.Column("description", sa.Text()),
        sa.Column("quantity", sa.Float()),
        sa.Column("unit", sa.String(length=50)),
        sa.Column("unit_price", sa.Float()),
        sa.Column("total_price", sa.Float()),
        sa.Column("confidence", sa.Float()),
    )
    op.create_index("ix_budget_lines_budget_id", "budget_lines", ["budget_id"])
    op.create_index("ix_budget_lines_reference", "budget_lines", ["reference"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_number", sa.String(length=120)),
        sa.Column("supplier_name", sa.String(length=255)),
        sa.Column("client_name", sa.String(length=255)),
        sa.Column("date", sa.Date()),
        sa.Column("total_amount", sa.Float()),
        sa.Column("currency", sa.String(length=12)),
        sa.Column("related_budget_id", sa.Integer(), sa.ForeignKey("budgets.id", ondelete="SET NULL")),
        sa.Column("confidence", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_orders_document_id", "orders", ["document_id"])
    op.create_index("ix_orders_order_number", "orders", ["order_number"])
    op.create_index("ix_orders_supplier_name", "orders", ["supplier_name"])
    op.create_index("ix_orders_client_name", "orders", ["client_name"])
    op.create_index("ix_orders_related_budget_id", "orders", ["related_budget_id"])

    op.create_table(
        "order_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reference", sa.String(length=120)),
        sa.Column("description", sa.Text()),
        sa.Column("quantity", sa.Float()),
        sa.Column("unit", sa.String(length=50)),
        sa.Column("unit_price", sa.Float()),
        sa.Column("total_price", sa.Float()),
        sa.Column("confidence", sa.Float()),
    )
    op.create_index("ix_order_lines_order_id", "order_lines", ["order_id"])
    op.create_index("ix_order_lines_reference", "order_lines", ["reference"])

    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_name", sa.String(length=255)),
        sa.Column("scale_text", sa.String(length=80)),
        sa.Column("scale_ratio", sa.Float()),
        sa.Column("scale_confidence", sa.Float()),
        sa.Column("unit", sa.String(length=20)),
        sa.Column("has_valid_scale", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_plans_document_id", "plans", ["document_id"])
    op.create_index("ix_plans_project_name", "plans", ["project_name"])
    op.create_index("ix_plans_has_valid_scale", "plans", ["has_valid_scale"])

    op.create_table(
        "plan_rooms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=180)),
        sa.Column("area_m2", sa.Float()),
        sa.Column("width_m", sa.Float()),
        sa.Column("length_m", sa.Float()),
        sa.Column("polygon_json", sa.JSON()),
        sa.Column("confidence", sa.Float()),
        sa.Column("source", sa.String(length=80)),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_plan_rooms_plan_id", "plan_rooms", ["plan_id"])
    op.create_index("ix_plan_rooms_name", "plan_rooms", ["name"])

    op.create_table(
        "plan_dimensions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("raw_text", sa.Text()),
        sa.Column("value", sa.Float()),
        sa.Column("unit", sa.String(length=20)),
        sa.Column("value_m", sa.Float()),
        sa.Column("page_number", sa.Integer()),
        sa.Column("bbox_x1", sa.Float()),
        sa.Column("bbox_y1", sa.Float()),
        sa.Column("bbox_x2", sa.Float()),
        sa.Column("bbox_y2", sa.Float()),
        sa.Column("confidence", sa.Float()),
    )
    op.create_index("ix_plan_dimensions_plan_id", "plan_dimensions", ["plan_id"])

    op.create_table(
        "ai_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_questions_user_id", "ai_questions", ["user_id"])

    op.create_table(
        "ai_answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("ai_questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("model_name", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_answers_question_id", "ai_answers", ["question_id"])

    op.create_table(
        "ai_answer_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("answer_id", sa.Integer(), sa.ForeignKey("ai_answers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("page_number", sa.Integer()),
        sa.Column("block_id", sa.Integer(), sa.ForeignKey("document_blocks.id", ondelete="SET NULL")),
        sa.Column("relevance_score", sa.Float()),
        sa.Column("excerpt", sa.Text()),
    )
    op.create_index("ix_ai_answer_sources_answer_id", "ai_answer_sources", ["answer_id"])
    op.create_index("ix_ai_answer_sources_document_id", "ai_answer_sources", ["document_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("entity_type", sa.String(length=120)),
        sa.Column("entity_id", sa.Integer()),
        sa.Column("details_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_entity_type", "audit_logs", ["entity_type"])
    op.create_index("ix_audit_logs_entity_id", "audit_logs", ["entity_id"])


def downgrade() -> None:
    for table in [
        "audit_logs",
        "ai_answer_sources",
        "ai_answers",
        "ai_questions",
        "plan_dimensions",
        "plan_rooms",
        "plans",
        "order_lines",
        "orders",
        "budget_lines",
        "budgets",
        "extraction_jobs",
        "document_chunks",
        "document_entities",
        "document_blocks",
        "document_pages",
        "documents",
        "users",
    ]:
        op.drop_table(table)

