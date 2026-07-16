"""Persist native CAD entities and dimension provenance.

Revision ID: 0062_cad_structured_extraction
Revises: 0061_contextual_occurrence_provenance
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op


revision = "0062_cad_structured_extraction"
down_revision = "0061_contextual_occurrence_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("source_format", sa.String(20)))
    op.add_column("plans", sa.Column("cad_unit", sa.String(20)))
    op.add_column("plans", sa.Column("cad_extents_json", sa.JSON()))
    op.add_column("plans", sa.Column("cad_metadata_json", sa.JSON()))
    op.add_column("plans", sa.Column("coordinate_transform_json", sa.JSON()))
    op.add_column("plans", sa.Column("conversion_provenance_json", sa.JSON()))

    op.add_column("plan_dimensions", sa.Column("source_method", sa.String(40)))
    op.add_column("plan_dimensions", sa.Column("source_entity_handle", sa.String(80)))
    op.add_column("plan_dimensions", sa.Column("layer", sa.String(255)))
    op.add_column("plan_dimensions", sa.Column("native_value", sa.Float()))
    op.add_column("plan_dimensions", sa.Column("native_unit", sa.String(20)))
    op.add_column("plan_dimensions", sa.Column("unit_source", sa.String(40)))
    op.add_column("plan_dimensions", sa.Column("coordinates_json", sa.JSON()))
    op.add_column(
        "plan_dimensions",
        sa.Column("validation_status", sa.String(30), nullable=False, server_default=sa.text("'auto'")),
    )
    op.add_column(
        "plan_dimensions",
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_plan_dimensions_source_method", "plan_dimensions", ["source_method"])
    op.create_index(
        "ix_plan_dimensions_source_entity_handle",
        "plan_dimensions",
        ["source_entity_handle"],
    )

    op.create_table(
        "plan_cad_entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_handle", sa.String(80)),
        sa.Column("entity_type", sa.String(60), nullable=False),
        sa.Column("layer", sa.String(255)),
        sa.Column("layout", sa.String(120)),
        sa.Column("geometry_json", sa.JSON()),
        sa.Column("properties_json", sa.JSON()),
        sa.Column(
            "source_method",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'cad_dxf'"),
        ),
        sa.Column("confidence", sa.Float()),
        sa.Column(
            "validation_status",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'auto'"),
        ),
        sa.UniqueConstraint(
            "plan_id",
            "entity_handle",
            "source_method",
            name="uq_plan_cad_entities_plan_handle_source",
        ),
    )
    op.create_index("ix_plan_cad_entities_plan_id", "plan_cad_entities", ["plan_id"])
    op.create_index("ix_plan_cad_entities_entity_type", "plan_cad_entities", ["entity_type"])
    op.create_index("ix_plan_cad_entities_layer", "plan_cad_entities", ["layer"])


def downgrade() -> None:
    op.drop_index("ix_plan_cad_entities_layer", table_name="plan_cad_entities")
    op.drop_index("ix_plan_cad_entities_entity_type", table_name="plan_cad_entities")
    op.drop_index("ix_plan_cad_entities_plan_id", table_name="plan_cad_entities")
    op.drop_table("plan_cad_entities")
    op.drop_index("ix_plan_dimensions_source_entity_handle", table_name="plan_dimensions")
    op.drop_index("ix_plan_dimensions_source_method", table_name="plan_dimensions")
    op.drop_column("plan_dimensions", "needs_review")
    op.drop_column("plan_dimensions", "validation_status")
    op.drop_column("plan_dimensions", "coordinates_json")
    op.drop_column("plan_dimensions", "unit_source")
    op.drop_column("plan_dimensions", "native_unit")
    op.drop_column("plan_dimensions", "native_value")
    op.drop_column("plan_dimensions", "layer")
    op.drop_column("plan_dimensions", "source_entity_handle")
    op.drop_column("plan_dimensions", "source_method")
    op.drop_column("plans", "cad_metadata_json")
    op.drop_column("plans", "conversion_provenance_json")
    op.drop_column("plans", "coordinate_transform_json")
    op.drop_column("plans", "cad_extents_json")
    op.drop_column("plans", "cad_unit")
    op.drop_column("plans", "source_format")
