from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models import ConstructionWorkItem, Document, Plan, WorkChapter
from app.services.plan_extraction import persist_plan_extraction
from app.services.technical_pipeline import process_technical_document


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_measurements_pipeline_persists_idempotent_work_items():
    db = _session()
    document = Document(
        original_filename="mediciones.pdf",
        file_hash="technical-measurements",
        document_type="mediciones_obra",
    )
    db.add(document)
    db.flush()
    text = """1 ESTRUCTURA
1.1 CIMENTACION
1.1.1 Excavacion m3 45,00 12,50 562,50
1.1.2 Hormigonado m3 32,00 85,00 2720,00
"""

    first = process_technical_document(
        db, document.id, text, document.original_filename, document.document_type
    )
    db.commit()
    second = process_technical_document(
        db, document.id, text, document.original_filename, document.document_type
    )
    db.commit()

    assert first.work_chapters_extracted == 2
    assert first.work_items_extracted == 2
    assert first.total_budget == 3282.5
    assert second.total_budget == first.total_budget
    assert db.scalar(select(func.count(WorkChapter.id))) == 2
    assert db.scalar(select(func.count(ConstructionWorkItem.id))) == 2
    extracted = list(db.scalars(select(ConstructionWorkItem).order_by(ConstructionWorkItem.code)).all())
    assert extracted[0].quantity == 45.0
    assert extracted[0].unit_price == 12.5
    assert extracted[0].total_price == 562.5


def test_persisted_plan_keeps_phase_revision_and_feeds_technical_summary():
    db = _session()
    document = Document(
        original_filename="planta_baja.pdf",
        file_hash="technical-plan",
        document_type="plano",
        confidence=0.9,
    )
    db.add(document)
    db.flush()
    text = """Plano de reforma
Escala 1:100
Planta Baja
Rev: B
Cocina 12 m2
"""

    persisted = persist_plan_extraction(db, document, text)
    db.commit()
    plan = db.scalar(select(Plan).where(Plan.document_id == document.id))
    summary = process_technical_document(
        db, document.id, text, document.original_filename, document.document_type
    )

    assert persisted.plan is not None
    assert plan is not None
    assert plan.project_phase == "PLANTA BAJA"
    assert plan.revision == "B"
    assert summary.plan_id == plan.id
    assert summary.rooms_extracted >= 1
