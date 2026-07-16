from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models import Document, HotelChain
from app.models.project import DocumentOccurrence


def test_repair_selects_only_business_images_in_image_occurrences(monkeypatch):
    from app.commands.repair_contextual_classification import repair_contextual_classifications

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        brand = HotelChain(name="Marca")
        db.add(brand)
        db.flush()
        candidate = Document(
            original_filename="foto.jpg",
            file_hash="candidate",
            extension=".jpg",
            document_type="presupuesto",
        )
        safe = Document(
            original_filename="oferta.pdf",
            file_hash="safe",
            extension=".pdf",
            document_type="presupuesto",
        )
        db.add_all([candidate, safe])
        db.flush()
        db.add_all(
            [
                DocumentOccurrence(
                    document_id=candidate.id,
                    source_path="upload/1/Marca/Presupuesto 1/IMAGENES/foto.jpg",
                    source_root="upload/1",
                    year=2025,
                    brand_id=brand.id,
                    category="imagenes",
                    original_filename="foto.jpg",
                ),
                DocumentOccurrence(
                    document_id=safe.id,
                    source_path="upload/1/Marca/Presupuesto 1/PDF/oferta.pdf",
                    source_root="upload/1",
                    year=2025,
                    brand_id=brand.id,
                    category="presupuestos",
                    original_filename="oferta.pdf",
                ),
            ]
        )
        db.commit()

    def fake_reclassify(db, document):
        document.document_type = "foto_producto"
        return False

    monkeypatch.setattr(
        "app.services.document_processing_core._process_classification_only", fake_reclassify
    )
    preview = repair_contextual_classifications(dry_run=True, session_factory=sessions)
    result = repair_contextual_classifications(dry_run=False, session_factory=sessions)

    with sessions() as db:
        documents = {document.file_hash: document for document in db.scalars(select(Document)).all()}
    assert preview["candidates"] == 1
    assert result["reclassified"] == 1
    assert documents["candidate"].document_type == "foto_producto"
    assert documents["safe"].document_type == "presupuesto"
