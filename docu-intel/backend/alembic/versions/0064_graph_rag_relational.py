"""Sprint GraphRAG (1/2) — relational tables for the entity/relation graph.

This migration introduces the seven tables that back the Graph RAG
feature described in ``PLAN_ARQUITECTURA_PGVECTOR_GRAPH_RAG.md``
(§3 — Graph RAG sobre tablas relacionales de PostgreSQL).

The design is intentionally database-agnostic: no PostgreSQL-only
types (no ``tsvector``, no ``vector``, no ``JSONB`` beyond what the
existing models already use). All relationships are expressed with
plain foreign keys; the application traverses the graph with standard
SQL (``JOIN``/``EXISTS``/recursive CTEs). No graph extension
(Neo4j, Apache AGE, …) is involved.

Tables
------
* ``graph_entities``        — global catalogue of entities, deduplicated
                              by ``(tenant_id, normalized_value)``.
* ``graph_entity_mentions`` — every appearance of an entity in a
                              chunk/page/block (many-to-one).
* ``graph_relations``       — verified ``(source, type, target)`` edges
                              between two entities.
* ``graph_relation_evidence`` — verbatim quote(s) that back a relation.
* ``graph_extraction_jobs`` — idempotent, resumable extraction runs.
* ``graph_extraction_errors`` — per-job failure log (retry fodder).
* ``graph_review_queue``    — entities / relations awaiting human review.

Why we do *not* partition these tables yet
-----------------------------------------
``PLAN_ARQUITECTURA_PGVECTOR_GRAPH_RAG.md`` §3.1 is explicit: do not
pre-emptively partition ``graph_relation_evidence`` or
``graph_extraction_errors`` until §2.2 measures confirm the volume
warrants the operational cost. The migration creates plain tables;
a future migration can convert them to ``PARTITION BY RANGE
(created_at)`` following the ``0033_partition_audit_and_jobs``
pattern when the data justifies it.

Why we keep ``document_entities`` alongside ``graph_entities``
--------------------------------------------------------------
``document_entities`` (in ``app/models/document.py``) is the
per-document extraction layer. ``graph_entities`` is the global,
tenant-scoped, deduplicated catalogue that consolidates mentions
across documents. The two coexist on purpose: the former answers
"what did we extract from *this* document?"; the latter answers
"what entities exist in *this tenant*, and which documents
reference them?". Downstream services fan out from the per-document
extractions to populate the global catalogue.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0064_graph_rag_relational"
down_revision = "0063_ai_answer_fallback_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # graph_entities — global, tenant-scoped catalogue.
    #
    # ``(tenant_id, normalized_value)`` is unique *only* when
    # ``normalized_value`` is not NULL (partial unique index), so that
    # free-form entities that could not be normalized still co-exist
    # in the catalogue without forcing a synthetic key. ``entity_type``
    # participates in the natural key because the same normalized
    # string can represent different things depending on the type
    # ("100" as a price vs. "100" as a quantity).
    # ------------------------------------------------------------------
    op.create_table(
        "graph_entities",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("hotel_chains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=True),
        sa.Column("canonical_label", sa.String(length=255), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("mention_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_graph_entities_tenant_type", "graph_entities", ["tenant_id", "entity_type"])
    op.create_index(
        "uq_graph_entities_tenant_normalized",
        "graph_entities",
        ["tenant_id", "normalized_value", "entity_type"],
        unique=True,
        postgresql_where=sa.text("normalized_value IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # graph_entity_mentions — pivot from a chunk/page/block to an entity.
    #
    # One entity can be mentioned in many places; one mention pins
    # the entity to a concrete evidence location. ``chunk_id``,
    # ``page_number`` and ``block_id`` are nullable because the same
    # relation layer can attach to either a chunk (most common), a
    # single page, or a structural block. Exactly one of the three
    # should be non-null in practice; the application layer enforces
    # that invariant.
    # ------------------------------------------------------------------
    op.create_table(
        "graph_entity_mentions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "entity_id",
            sa.BigInteger(),
            sa.ForeignKey("graph_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_chunk_id", sa.BigInteger(), sa.ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=True),
        sa.Column("document_page_id", sa.BigInteger(), sa.ForeignKey("document_pages.id", ondelete="CASCADE"), nullable=True),
        sa.Column("document_block_id", sa.BigInteger(), sa.ForeignKey("document_blocks.id", ondelete="CASCADE"), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_graph_entity_mentions_entity", "graph_entity_mentions", ["entity_id"])
    op.create_index(
        "ix_graph_entity_mentions_document_chunk",
        "graph_entity_mentions",
        ["document_id", "document_chunk_id"],
    )

    # ------------------------------------------------------------------
    # graph_relations — verified edges between two entities.
    #
    # ``relation_type`` is a free-form short string (e.g. ``"is_issued_by"``,
    # ``"references"``, ``"amends"``). The catalogue of allowed types is
    # enforced at the application layer; the schema stays open so new
    # relations can be added without a migration.
    #
    # ``(source_entity_id, target_entity_id, relation_type)`` is unique
    # so re-running an extraction job is idempotent: a duplicate
    # relation becomes a no-op via ``ON CONFLICT DO NOTHING``.
    # ------------------------------------------------------------------
    op.create_table(
        "graph_relations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "source_entity_id",
            sa.BigInteger(),
            sa.ForeignKey("graph_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_entity_id",
            sa.BigInteger(),
            sa.ForeignKey("graph_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(length=80), nullable=False),
        sa.Column("polarity", sa.String(length=20), nullable=False, server_default="asserted"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="verified"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "uq_graph_relations_edge",
        "graph_relations",
        ["source_entity_id", "target_entity_id", "relation_type"],
        unique=True,
    )
    op.create_index("ix_graph_relations_source_type", "graph_relations", ["source_entity_id", "relation_type"])
    op.create_index("ix_graph_relations_target", "graph_relations", ["target_entity_id"])

    # ------------------------------------------------------------------
    # graph_relation_evidence — verbatim quotes that back a relation.
    #
    # A relation must have at least one evidence row before it can be
    # marked ``status='verified'``; the application enforces this in
    # the verification step (see ``PLAN_ARQUITECTURA_PGVECTOR_GRAPH_RAG.md``
    # §3.2). The table is a candidate for monthly partitioning
    # following ``0033`` once §2.2 measures confirm the volume — until
    # then it stays as a plain table to keep the operational footprint
    # small.
    # ------------------------------------------------------------------
    op.create_table(
        "graph_relation_evidence",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "relation_id",
            sa.BigInteger(),
            sa.ForeignKey("graph_relations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_chunk_id", sa.BigInteger(), sa.ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("extractor_version", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_graph_relation_evidence_relation", "graph_relation_evidence", ["relation_id"])
    op.create_index("ix_graph_relation_evidence_document", "graph_relation_evidence", ["document_id"])

    # ------------------------------------------------------------------
    # graph_extraction_jobs — idempotent, resumable extraction runs.
    #
    # ``scope_key`` lets the same job re-run safely: the worker keys
    # on ``(document_id, extractor_version)`` so a partial run is
    # detectable and resumable. ``status`` mirrors the pattern used
    # by ``extraction_jobs``.
    # ------------------------------------------------------------------
    op.create_table(
        "graph_extraction_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("extractor_version", sa.String(length=40), nullable=False),
        sa.Column("scope_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entities_proposed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("relations_proposed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "uq_graph_extraction_jobs_scope",
        "graph_extraction_jobs",
        ["document_id", "extractor_version", "scope_key"],
        unique=True,
    )
    op.create_index("ix_graph_extraction_jobs_status_created", "graph_extraction_jobs", ["status", "created_at"])

    # ------------------------------------------------------------------
    # graph_extraction_errors — per-job failure log.
    #
    # Splitting errors from the job itself keeps the hot path
    # (``status='succeeded'`` jobs) free of large error blobs and
    # makes it easy to retry only the failed scope. The table is a
    # candidate for monthly partitioning once §2.2 measures confirm
    # the volume; until then it stays unpartitioned.
    # ------------------------------------------------------------------
    op.create_table(
        "graph_extraction_errors",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.BigInteger(),
            sa.ForeignKey("graph_extraction_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(length=60), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("retries", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_graph_extraction_errors_job", "graph_extraction_errors", ["job_id"])
    op.create_index("ix_graph_extraction_errors_unresolved", "graph_extraction_errors", ["resolved", "created_at"])

    # ------------------------------------------------------------------
    # graph_review_queue — entities and relations pending human review.
    #
    # ``target_type`` is either ``'entity'`` or ``'relation'`` and
    # ``target_id`` points at the corresponding row. Storing the
    # reference polymorphically (rather than two parallel tables) keeps
    # the review UX (single queue) simple; the integrity check
    # (target exists) is enforced at the application layer because
    # PostgreSQL cannot express a FK that fans out to two parent
    # tables. The ``status`` index supports the review dashboard's
    # default "pending" filter.
    # ------------------------------------------------------------------
    op.create_table(
        "graph_review_queue",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("submitted_by_job_id", sa.BigInteger(), sa.ForeignKey("graph_extraction_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assigned_to_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("decided_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("target_type IN ('entity', 'relation')", name="ck_graph_review_queue_target_type"),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'escalated')", name="ck_graph_review_queue_status"),
    )
    op.create_index("ix_graph_review_queue_status_created", "graph_review_queue", ["status", "created_at"])
    op.create_index(
        "ix_graph_review_queue_target",
        "graph_review_queue",
        ["target_type", "target_id"],
    )


def downgrade() -> None:
    # Drop in reverse dependency order so no FK is left dangling.
    op.drop_index("ix_graph_review_queue_target", table_name="graph_review_queue")
    op.drop_index("ix_graph_review_queue_status_created", table_name="graph_review_queue")
    op.drop_table("graph_review_queue")
    op.drop_index("ix_graph_extraction_errors_unresolved", table_name="graph_extraction_errors")
    op.drop_index("ix_graph_extraction_errors_job", table_name="graph_extraction_errors")
    op.drop_table("graph_extraction_errors")
    op.drop_index("ix_graph_extraction_jobs_status_created", table_name="graph_extraction_jobs")
    op.drop_index("uq_graph_extraction_jobs_scope", table_name="graph_extraction_jobs")
    op.drop_table("graph_extraction_jobs")
    op.drop_index("ix_graph_relation_evidence_document", table_name="graph_relation_evidence")
    op.drop_index("ix_graph_relation_evidence_relation", table_name="graph_relation_evidence")
    op.drop_table("graph_relation_evidence")
    op.drop_index("ix_graph_relations_target", table_name="graph_relations")
    op.drop_index("ix_graph_relations_source_type", table_name="graph_relations")
    op.drop_index("uq_graph_relations_edge", table_name="graph_relations")
    op.drop_table("graph_relations")
    op.drop_index("ix_graph_entity_mentions_document_chunk", table_name="graph_entity_mentions")
    op.drop_index("ix_graph_entity_mentions_entity", table_name="graph_entity_mentions")
    op.drop_table("graph_entity_mentions")
    op.drop_index("uq_graph_entities_tenant_normalized", table_name="graph_entities")
    op.drop_index("ix_graph_entities_tenant_type", table_name="graph_entities")
    op.drop_table("graph_entities")
