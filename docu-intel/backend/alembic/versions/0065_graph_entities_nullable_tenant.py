"""Make ``graph_entities.tenant_id`` nullable (regression 2026-07-16).

The original 0064 migration declared ``tenant_id INTEGER NOT NULL``
with a foreign key to ``hotel_chains.id``. In a greenfield deployment
``hotel_chains`` is empty (the seed data has only ``budget_scopes``)
and the Graph RAG extractor refused to run with ``no hotel_chains row
for doc X``. The fix:

* Drop the FK to ``hotel_chains`` (we never enforced isolation on the
  relations table, only on the entities).
* Make ``tenant_id`` nullable: NULL means "no tenant association" —
  a single-tenant install, an admin upload without a budget scope, or
  a pre-chain-isolation legacy document.
* The application-side code keeps the chain lookup but treats
  ``tenant_id is None`` as a valid state (no per-tenant filtering
  applied, all relations share the global catalogue).

The change is forward-only: existing rows keep their ``tenant_id``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0065_graph_entities_nullable_tenant"
down_revision = "0064_graph_rag_relational"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the FK constraint first. The constraint name is the
    # auto-generated one from 0064 (Postgres convention).
    op.drop_constraint(
        "graph_entities_tenant_id_fkey",
        "graph_entities",
        type_="foreignkey",
    )
    # Make the column nullable.
    op.alter_column(
        "graph_entities",
        "tenant_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "graph_entities",
        "tenant_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_foreign_key(
        "graph_entities_tenant_id_fkey",
        "graph_entities",
        "hotel_chains",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
