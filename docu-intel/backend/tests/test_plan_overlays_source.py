from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models import Document, Plan, PlanDimension, PlanRoom


def test_plan_overlays_return_source_backed_room_and_dimension(monkeypatch):
    from app.api.routes import plans as route

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    document = Document(original_filename="planta.pdf", file_hash="plan", source_path="/planta.pdf")
    db.add(document)
    db.flush()
    plan = Plan(document_id=document.id, project_name="Hotel", has_valid_scale=True)
    db.add(plan)
    db.flush()
    db.add_all([
        PlanDimension(
            plan_id=plan.id,
            raw_text="2.40 m",
            value_m=2.4,
            page_number=1,
            bbox_x1=0.1,
            bbox_y1=0.2,
            bbox_x2=0.3,
            bbox_y2=0.25,
            confidence=0.88,
        ),
        PlanRoom(
            plan_id=plan.id,
            name="Sala",
            polygon_json=[{"x": 0.4, "y": 0.4}, {"x": 0.6, "y": 0.6}],
            confidence=0.8,
            source="ocr_room",
        ),
    ])
    db.commit()
    monkeypatch.setattr(route, "resolve_user_access_scope", lambda db, user: SimpleNamespace())
    monkeypatch.setattr(route, "filter_records_by_document_scope", lambda db, records, scope: records)

    overlays = route.get_plan_overlays(plan.id, page=None, db=db, user=SimpleNamespace())

    assert {(overlay.region_type, overlay.source_document, overlay.source_kind) for overlay in overlays} >= {
        ("dimension", "planta.pdf", "ocr_dimension"),
        ("room", "planta.pdf", "ocr_room"),
    }
