from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models import Budget, Document, HotelChain
from app.models.project import DocumentOccurrence
from app.services.business_extraction import persist_business_extraction


def test_budget_uses_verified_occurrence_code_when_body_has_no_number():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    brand = HotelChain(name="Marca")
    db.add(brand)
    db.flush()
    document = Document(
        original_filename="oferta.pdf",
        file_hash="contextual-budget",
        document_type="presupuesto",
        confidence=0.9,
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentOccurrence(
            document_id=document.id,
            source_path="upload/1/Marca/Presupuesto 252700/PDF/oferta.pdf",
            source_root="upload/1",
            year=2025,
            brand_id=brand.id,
            original_filename="oferta.pdf",
            resolved_budget_code="252700",
            association_status="folder_only",
        )
    )
    db.flush()

    persist_business_extraction(
        db,
        document,
        text="""Cliente: Hotel Demo
Total presupuesto: 120,00 EUR
""",
    )
    budget = db.scalar(select(Budget).where(Budget.document_id == document.id))

    assert budget is not None
    assert budget.budget_number == "252700"
    assert budget.budget_number_normalized == "252700"
