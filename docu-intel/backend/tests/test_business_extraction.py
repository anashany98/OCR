from app.services.business_extraction import extract_budget, extract_order


def test_extracts_basic_budget_fields_and_lines():
    text = """
    PRESUPUESTO 2026/143
    Cliente: Talleres Norte SL
    Fecha: 12/05/2026
    Estado: Aceptado

    REF-001 Encimera porcelanica 2 ud 120,50 241,00
    ABC123 Fregadero bajo encimera 1 ud 89,90 89,90

    Total presupuesto: 330,90 EUR
    """

    result = extract_budget(document_id=7, text=text, document_confidence=0.91)

    assert result is not None
    assert result.budget_number == "2026/143"
    assert result.client_name == "Talleres Norte SL"
    assert result.date.isoformat() == "2026-05-12"
    assert result.total_amount == 330.90
    assert result.currency == "EUR"
    assert result.status == "aceptado"
    assert result.accepted_detected is True
    assert result.lines[0].reference == "REF-001"
    assert result.lines[0].quantity == 2
    assert result.lines[1].reference == "ABC123"


def test_extracts_basic_order_fields_and_related_budget_number():
    text = """
    Pedido 2026/154
    Proveedor: Herrajes Centro
    Cliente: Talleres Norte SL
    Fecha pedido: 14-05-2026
    Presupuesto relacionado: 2026/143

    REF-001 Encimera porcelanica 2 ud 120,50 241,00

    Total pedido: 241,00 €
    """

    result = extract_order(document_id=8, text=text, document_confidence=0.88)

    assert result is not None
    assert result.order_number == "2026/154"
    assert result.supplier_name == "Herrajes Centro"
    assert result.client_name == "Talleres Norte SL"
    assert result.date.isoformat() == "2026-05-14"
    assert result.total_amount == 241.00
    assert result.currency == "EUR"
    assert result.related_budget_number == "2026/143"
    assert result.lines[0].reference == "REF-001"




def test_order_without_required_date_needs_review_instead_of_persisting_invalid_row(tmp_path):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database.base import Base
    from app.models import Document, Order
    from app.services.business_extraction import persist_business_extraction

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)

    with SessionLocal() as db:
        document = Document(
            original_filename="pedido.txt",
            stored_filename="aa/pedido.txt",
            source_path="/data/input/pedidos/pedido.txt",
            file_hash="a" * 64,
            mime_type="text/plain",
            extension=".txt",
            file_size=10,
            document_type="pedido",
            status="processing",
            confidence=0.9,
        )
        db.add(document)
        db.flush()

        result = persist_business_extraction(
            db,
            document,
            "Pedido P-123 para Hotel Demo. Referencia ABC123 sin fecha visible.",
        )
        db.commit()

        orders = list(db.scalars(select(Order)).all())

    assert result.needs_review is True
    assert result.order is None
    assert orders == []
