from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.routes.plans import (
    ConfirmRequest,
    _cad_dimension_overlay_bbox,
    bulk_update,
    confirm_dimension,
)
from app.database.base import Base
from app.models import Document, Plan, PlanCadEntity, PlanDimension, User
from app.parsers.types import CadDimensionEntity, CadExtraction, CadGeometryEntity, CadMetadata
from app.schemas.business import PlanBulkUpdate, PlanDimensionCreate
from app.services.plan_extraction import persist_plan_extraction
from app.tools.plans import get_plan_cad_context


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _plan_and_admin(db):
    document = Document(
        original_filename="planta.dxf",
        file_hash="cad-safety",
        document_type="plano",
        confidence=0.9,
    )
    user = User(
        email="admin@example.test",
        name="Admin",
        password_hash="not-used-in-test",
        role="admin",
    )
    db.add_all((document, user))
    db.flush()
    return document, user


def _cad_extraction() -> CadExtraction:
    return CadExtraction(
        metadata=CadMetadata(source_format="dxf", unit="mm", layout="modelspace"),
        geometry=(
            CadGeometryEntity(
                entity_handle="10",
                entity_type="line",
                layer="WALLS",
                geometry={"start": [0, 0], "end": [1000, 0]},
            ),
        ),
        dimensions=(
            CadDimensionEntity(
                entity_handle="20",
                layer="DIMS",
                value=1000.0,
                displayed_text="1000",
                native_unit="mm",
                unit_source="drawing_unit",
                normalized_value_m=1.0,
            ),
        ),
    )


def test_reprocessing_without_native_cad_preserves_existing_cad_evidence():
    db = _session()
    document, _ = _plan_and_admin(db)
    text = "Plano de reforma\nEscala 1:100"

    persist_plan_extraction(db, document, text, cad_extraction=_cad_extraction())
    db.commit()
    plan = db.scalar(select(Plan).where(Plan.document_id == document.id))
    assert plan is not None

    persist_plan_extraction(db, document, text, preserve_existing_cad=True)
    db.commit()

    assert db.scalar(select(PlanCadEntity).where(PlanCadEntity.plan_id == plan.id)) is not None
    dimensions = list(
        db.scalars(select(PlanDimension).where(PlanDimension.plan_id == plan.id)).all()
    )
    assert [(dimension.source_method, dimension.source_entity_handle) for dimension in dimensions] == [
        ("cad_dxf", "20")
    ]


def test_bulk_save_replaces_only_manual_dimensions():
    db = _session()
    document, user = _plan_and_admin(db)
    plan = Plan(document_id=document.id)
    db.add(plan)
    db.flush()
    db.add_all(
        (
            PlanDimension(
                plan_id=plan.id,
                raw_text="1000",
                value=1000.0,
                unit="mm",
                value_m=1.0,
                source_method="cad_dxf",
                source_entity_handle="20",
                validation_status="auto",
            ),
            PlanDimension(
                plan_id=plan.id,
                raw_text="2 m",
                value=2.0,
                unit="m",
                value_m=2.0,
                source_method="manual",
                validation_status="confirmed",
            ),
        )
    )
    db.commit()

    bulk_update(
        plan.id,
        PlanBulkUpdate(dimensions=[PlanDimensionCreate(raw_text="3 m", value=3.0)]),
        db,
        user,
    )

    dimensions = list(
        db.scalars(select(PlanDimension).where(PlanDimension.plan_id == plan.id)).all()
    )
    assert {(dimension.source_method, dimension.raw_text) for dimension in dimensions} == {
        ("cad_dxf", "1000"),
        ("manual", "3 m"),
    }


def test_confirm_dimension_resolves_review_state():
    db = _session()
    document, user = _plan_and_admin(db)
    plan = Plan(document_id=document.id)
    db.add(plan)
    db.flush()
    dimension = PlanDimension(
        plan_id=plan.id,
        raw_text="?",
        confidence=0.5,
        source_method="cad_dxf",
        validation_status="needs_review",
        needs_review=True,
    )
    db.add(dimension)
    db.commit()

    confirmed = confirm_dimension(
        plan.id,
        dimension.id,
        ConfirmRequest(action="confirm"),
        db,
        user,
    )

    assert confirmed.validation_status == "confirmed"
    assert confirmed.needs_review is False


def test_cad_context_prioritizes_exact_identifier_beyond_legacy_preview_limit():
    db = _session()
    document, _ = _plan_and_admin(db)
    plan = Plan(document_id=document.id, source_format="dxf")
    db.add(plan)
    db.flush()
    db.add_all(
        PlanCadEntity(
            plan_id=plan.id,
            entity_handle=str(index),
            entity_type="line",
            layer="WALLS",
            source_method="cad_dxf",
            validation_status="auto",
        )
        for index in range(150)
    )
    db.add(
        PlanCadEntity(
            plan_id=plan.id,
            entity_handle="M3",
            entity_type="text",
            layer="MARKERS",
            geometry_json={"insertion_point": [10, 10]},
            properties_json={"text": "M3"},
            source_method="cad_dxf",
            validation_status="auto",
        )
    )
    db.add_all(
        (
            PlanDimension(
                plan_id=plan.id,
                raw_text="cota cercana",
                source_method="cad_dxf",
                coordinates_json={"text_point": [11, 10]},
                validation_status="auto",
            ),
            PlanDimension(
                plan_id=plan.id,
                raw_text="cota lejana",
                source_method="cad_dxf",
                coordinates_json={"text_point": [999, 999]},
                validation_status="auto",
            ),
        )
    )
    db.commit()

    row = get_plan_cad_context(db, document_id=document.id, query="¿Qué cotas tiene M3?")[0]

    assert row["cad_entities"][0].entity_handle == "M3"
    assert row["dimensions"][0].raw_text == "cota cercana"


def test_cad_dimension_coordinates_map_to_normalized_preview_overlay():
    plan = Plan(
        document_id=1,
        cad_extents_json={"x1": 0, "y1": 0, "x2": 100, "y2": 100},
        coordinate_transform_json={
            "canvas_width": 1400,
            "canvas_height": 1000,
            "margin": 50,
            "scale": 9.0,
            "extents": {"x1": 0, "y1": 0, "x2": 100, "y2": 100},
        },
    )

    bbox = _cad_dimension_overlay_bbox(
        plan,
        {"definition_points": [[0, 0], [100, 100]], "text_point": [50, 50]},
    )

    assert bbox is not None
    assert bbox[0] < 0.05 and bbox[1] < 0.06
    assert 0.68 < bbox[2] < 0.71
    assert bbox[3] > 0.94
