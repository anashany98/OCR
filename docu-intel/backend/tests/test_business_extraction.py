from app.services.business_extraction import (
    ValidationIssue,
    extract_budget,
    extract_invoice,
    extract_order,
    persist_business_extraction,
)
from app.services.business_extraction import (
    _extract_lines_for_document,
    _find_related_budget_id,
    _normalize_doc_number,
    _parse_amount,
    _status,
    _validate_extraction,
)
from app.services.extraction import extract_lines_from_pages
from app.services.extraction.provider_profiles import list_profiles, resolve_profile
from app.parsers.types import ExtractedBlock, ExtractedPage


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


def test_extracts_basic_invoice_fields():
    text = """
    FACTURA Nº F-2026-044
    Proveedor: Herrajes Centro SL
    CIF: B12345678
    Cliente: Talleres Norte SL
    Fecha factura: 18/05/2026
    Base imponible: 100,00 EUR
    IVA 21%: 21,00 EUR
    Total factura: 121,00 EUR
    """

    result = extract_invoice(document_id=9, text=text, document_confidence=0.9)

    assert result is not None
    assert result.invoice_number == "F-2026-044"
    assert result.supplier_name == "Herrajes Centro SL"
    assert result.supplier_tax_id == "B12345678"
    assert result.client_name == "Talleres Norte SL"
    assert result.date.isoformat() == "2026-05-18"
    assert result.taxable_base == 100.00
    assert result.vat_amount == 21.00
    assert result.total_amount == 121.00
    assert result.currency == "EUR"


def test_persist_invoice_extraction_creates_invoice_and_key_entities():
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database.base import Base
    from app.models import Document, DocumentEntity, Invoice
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
            original_filename="factura.txt",
            stored_filename="aa/factura.txt",
            source_path="/data/input/facturas/factura.txt",
            file_hash="b" * 64,
            mime_type="text/plain",
            extension=".txt",
            file_size=10,
            document_type="factura",
            status="processing",
            confidence=0.9,
        )
        db.add(document)
        db.flush()

        result = persist_business_extraction(
            db,
            document,
            """
            Factura nº F-200
            Proveedor: Proveedor Demo
            CIF: B87654321
            Cliente: Cliente Demo
            Fecha factura: 20/05/2026
            Base imponible: 100,00 EUR
            IVA 21%: 21,00 EUR
            Total factura: 121,00 EUR
            """,
        )
        db.commit()

        invoice = db.scalar(select(Invoice))
        entities = {
            entity.entity_type: entity.entity_value
            for entity in db.scalars(select(DocumentEntity)).all()
        }

    assert result.needs_review is False
    assert invoice is not None
    assert invoice.invoice_number == "F-200"
    assert invoice.supplier_name == "Proveedor Demo"
    assert invoice.client_name == "Cliente Demo"
    assert invoice.total_amount == 121.00
    assert entities["invoice_number"] == "F-200"
    assert entities["supplier_tax_id"] == "B87654321"
    assert entities["taxable_base"] == "100.00"
    assert entities["vat_amount"] == "21.00"




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


# ---------------------------------------------------------------------------
# New tests — added by the layout-aware / coherence / provider-profile PR.
# ---------------------------------------------------------------------------


def test_parse_amount_locale_es_es():
    """es-ES: ``.`` is thousands, ``,`` is decimal."""
    assert _parse_amount("1.234,56") == 1234.56
    assert _parse_amount("3,5") == 3.5
    assert _parse_amount("100,00") == 100.00
    # "1.234" with no comma is treated as es-ES thousands → 1234.0.
    assert _parse_amount("1.234") == 1234.0
    # "1,234" with no dot is also es-ES thousands → 1234.0.
    assert _parse_amount("1,234") == 1234.0


def test_parse_amount_locale_en_us():
    """en-US: ``,`` is thousands, ``.`` is decimal."""
    assert _parse_amount("1,234.56", "en-US") == 1234.56
    assert _parse_amount("12.5", "en-US") == 12.5
    # "1.234" with no comma is a valid en-US decimal.
    assert _parse_amount("1,234", "en-US") == 1234.0


def test_parse_amount_edge_cases():
    assert _parse_amount("") is None
    assert _parse_amount(None) is None
    assert _parse_amount("  0,50  ") == 0.5
    # NBSP gets stripped (some Spanish PDFs use them as thousands sep).
    assert _parse_amount("1\u00a0234,56") == 1234.56


def test_status_scoped_to_label_only():
    """A footer clause that contains 'cancelado' must not flip the
    status when the document has an explicit ``Estado:`` label."""
    text = """
    PRESUPUESTO 2026/143
    Cliente: Talleres Norte SL
    Estado: Aceptado

    Política de cancelación: 30 días desde la aceptación.
    Pendiente de revisión administrativa al cierre del ejercicio.
    """
    result = extract_budget(document_id=1, text=text, document_confidence=0.9)
    assert result.status == "aceptado"


def test_status_returns_none_when_no_label():
    """Without an explicit 'Estado:' label, status is None to avoid
    false positives from stray text like 'cancelado' in body text."""
    text = "Presupuesto 2026/143 para cliente X. Marcado como cancelado por el jefe de obra."
    result = extract_budget(document_id=1, text=text, document_confidence=0.9)
    assert result.status is None


def test_status_unknown_returns_none():
    text = "Presupuesto 2026/143 sin indicación de estado."
    result = extract_budget(document_id=1, text=text, document_confidence=0.9)
    assert result.status is None


def test_normalize_doc_number():
    assert _normalize_doc_number("2026/143") == "2026143"
    assert _normalize_doc_number("2026-143") == "2026143"
    assert _normalize_doc_number(" 2026 / 143 ") == "2026143"
    assert _normalize_doc_number("2026.143") == "2026143"
    assert _normalize_doc_number("PV-2026-044") == "pv2026044"
    assert _normalize_doc_number(None) == ""
    assert _normalize_doc_number("") == ""


def test_find_related_budget_id_handles_normalized_match():
    """An order that mentions the budget number with different
    separators (2026-143) must still resolve to the budget row
    stored as 2026/143."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database.base import Base
    from app.models import Budget
    from app.services.business_extraction import OrderExtraction

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as db:
        db.add(
            Budget(
                document_id=999,
                budget_number="2026/143",
                date=__import__("datetime").date(2026, 5, 12),
                confidence=0.9,
            )
        )
        db.commit()
        # The order mentions the same number with a hyphen.
        extraction = OrderExtraction(
            document_id=1000,
            order_number="P-1",
            supplier_name="X",
            client_name="Y",
            date=None,
            total_amount=10.0,
            currency="EUR",
            related_budget_number="2026-143",
            confidence=0.9,
        )
        resolved = _find_related_budget_id(db, extraction)
        assert resolved is not None
        assert resolved == 1  # the budget we just inserted


def test_validate_extraction_line_qty_price_total():
    from app.services.business_extraction import BudgetExtraction, ExtractedLine

    extraction = BudgetExtraction(
        document_id=1,
        budget_number="B-1",
        client_name=None,
        date=None,
        total_amount=120.0,  # sum(lines.total)=70+30=100, mismatch with total
        currency="EUR",
        status=None,
        accepted_detected=False,
        confidence=0.9,
        lines=[
            ExtractedLine("REF-1", "Item A", 2.0, "ud", 30.0, 70.0, 0.9),  # 2*30=60, but total says 70 → mismatch
            ExtractedLine("REF-2", "Item B", 1.0, "ud", 30.0, 30.0, 0.9),
        ],
    )
    issues = _validate_extraction(extraction)
    assert any(i.check == "line_qty_price_total" for i in issues)
    assert any(i.check == "subtotal_vs_total" for i in issues)


def test_validate_extraction_invoice_base_vat_total_mismatch():
    from app.services.business_extraction import InvoiceExtraction

    extraction = InvoiceExtraction(
        document_id=1,
        invoice_number="F-1",
        supplier_name="X",
        supplier_tax_id=None,
        client_name="Y",
        date=None,
        taxable_base=100.0,
        vat_amount=21.0,
        total_amount=130.0,  # should be 121.0
        currency="EUR",
        related_order_number=None,
        confidence=0.9,
    )
    issues = _validate_extraction(extraction)
    assert any(i.check == "base_vat_total" for i in issues)


def test_validate_extraction_clean_document_returns_no_issues():
    from app.services.business_extraction import InvoiceExtraction

    extraction = InvoiceExtraction(
        document_id=1,
        invoice_number="F-1",
        supplier_name="X",
        supplier_tax_id=None,
        client_name="Y",
        date=None,
        taxable_base=100.0,
        vat_amount=21.0,
        total_amount=121.0,
        currency="EUR",
        related_order_number=None,
        confidence=0.9,
    )
    issues = _validate_extraction(extraction)
    assert issues == []


def test_persist_invoice_flags_coherence_issue_via_validation():
    """A persist call where base + vat != total must set
    needs_review and populate review_reasons with a concrete cause."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database.base import Base
    from app.models import Document

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as db:
        document = Document(
            original_filename="factura.txt",
            stored_filename="aa/factura.txt",
            source_path="/data/input/facturas/factura.txt",
            file_hash="d" * 64,
            mime_type="text/plain",
            extension=".txt",
            file_size=10,
            document_type="factura",
            status="processing",
            confidence=0.9,
        )
        db.add(document)
        db.flush()
        result = persist_business_extraction(
            db,
            document,
            """
            Factura nº F-2
            Proveedor: X
            Cliente: Y
            Fecha factura: 20/05/2026
            Base imponible: 100,00 EUR
            IVA 21%: 21,00 EUR
            Total factura: 130,00 EUR
            """,
        )
        db.commit()
    assert result.needs_review is True
    assert any("iva" in r for r in result.review_reasons)
    assert any(isinstance(i, ValidationIssue) for i in result.validation_issues)


# ---------------------------------------------------------------------------
# Layout-aware line extraction
# ---------------------------------------------------------------------------


def test_extract_lines_from_pages_with_table_header():
    blocks = [
        ExtractedBlock("text", "REF", 1, bbox=(50, 100, 100, 120)),
        ExtractedBlock("text", "DESCRIPCIÓN", 1, bbox=(120, 100, 400, 120)),
        ExtractedBlock("text", "CANT", 1, bbox=(420, 100, 480, 120)),
        ExtractedBlock("text", "PRECIO UD", 1, bbox=(500, 100, 600, 120)),
        ExtractedBlock("text", "TOTAL", 1, bbox=(620, 100, 700, 120)),
        ExtractedBlock("text", "REF-001", 1, bbox=(50, 140, 110, 160)),
        ExtractedBlock("text", "Encimera porcelanica", 1, bbox=(120, 140, 400, 160)),
        ExtractedBlock("text", "2", 1, bbox=(420, 140, 480, 160)),
        ExtractedBlock("text", "120,50", 1, bbox=(500, 140, 600, 160)),
        ExtractedBlock("text", "241,00", 1, bbox=(620, 140, 700, 160)),
        ExtractedBlock("text", "ABC123", 1, bbox=(50, 180, 110, 200)),
        ExtractedBlock("text", "Fregadero", 1, bbox=(120, 180, 400, 200)),
        ExtractedBlock("text", "1", 1, bbox=(420, 180, 480, 200)),
        ExtractedBlock("text", "89,90", 1, bbox=(500, 180, 600, 200)),
        ExtractedBlock("text", "89,90", 1, bbox=(620, 180, 700, 200)),
    ]
    page = ExtractedPage(page_number=1, text="", width=800.0, height=300.0, blocks=blocks)
    lines = extract_lines_from_pages([page])
    assert len(lines) == 2
    assert lines[0].reference == "REF-001"
    assert lines[0].description == "Encimera porcelanica"
    assert lines[0].quantity == 2.0
    assert lines[0].unit_price == 120.5
    assert lines[0].total_price == 241.0
    assert lines[1].reference == "ABC123"
    assert lines[1].total_price == 89.9


def test_extract_lines_from_pages_falls_back_to_regex():
    """A page with no bounding boxes falls back to the legacy regex
    on the concatenated text."""
    page = ExtractedPage(
        page_number=1,
        text="REF-001 Encimera 2 ud 120,50 241,00\nABC123 Fregadero 1 ud 89,90 89,90",
        width=None,
        height=None,
        blocks=[],
    )
    lines = extract_lines_from_pages([page])
    assert len(lines) == 2
    assert lines[0].reference == "REF-001"


def test_persisted_document_block_exposes_complete_bbox_only():
    from app.models.document import DocumentBlock

    complete = DocumentBlock(bbox_x1=1, bbox_y1=2, bbox_x2=3, bbox_y2=4)
    incomplete = DocumentBlock(bbox_x1=1, bbox_y1=None, bbox_x2=3, bbox_y2=4)

    assert complete.bbox == (1.0, 2.0, 3.0, 4.0)
    assert incomplete.bbox is None


def test_extract_lines_for_document_uses_layout_when_pages_passed():
    blocks = [
        ExtractedBlock("text", "REF", 1, bbox=(50, 100, 100, 120)),
        ExtractedBlock("text", "DESCRIPCIÓN", 1, bbox=(120, 100, 400, 120)),
        ExtractedBlock("text", "CANT", 1, bbox=(420, 100, 480, 120)),
        ExtractedBlock("text", "TOTAL", 1, bbox=(620, 100, 700, 120)),
        ExtractedBlock("text", "R1", 1, bbox=(50, 140, 100, 160)),
        ExtractedBlock("text", "Item", 1, bbox=(120, 140, 400, 160)),
        ExtractedBlock("text", "3", 1, bbox=(420, 140, 480, 160)),
        ExtractedBlock("text", "150,00", 1, bbox=(620, 140, 700, 160)),
    ]
    page = ExtractedPage(page_number=1, text="", width=800.0, height=300.0, blocks=blocks)
    text = "R1 Item 3 ud 50,00 150,00"  # legacy regex would match
    lines = _extract_lines_for_document(text, pages=[page])
    assert len(lines) == 1
    # Layout-aware path: no 'unit' column in the synthetic header
    # (only 4 columns → fallback mapping).
    assert lines[0].reference == "R1"
    assert lines[0].total_price == 150.0


# ---------------------------------------------------------------------------
# Provider profiles
# ---------------------------------------------------------------------------


def test_resolve_profile_herrajes_centro():
    text = "FACTURA Nº F-2026-044\nProveedor: Herrajes Centro SL\nCIF: B12345678"
    profile = resolve_profile(text)
    assert profile.name == "herrajes_centro"
    assert profile.locale == "es-ES"


def test_resolve_profile_talleres_norte():
    text = "Quote from Talleres Norte SA\n..."
    profile = resolve_profile(text)
    assert profile.name == "talleres_norte"
    assert profile.locale == "en-US"


def test_resolve_profile_falls_back_to_generico():
    text = "Some random document with no supplier signal"
    profile = resolve_profile(text)
    assert profile.name == "generico"


def test_list_profiles_includes_generico_first():
    profiles = list_profiles()
    assert profiles[0].name == "generico"
    names = {p.name for p in profiles}
    assert "herrajes_centro" in names
    assert "talleres_norte" in names


# ---------------------------------------------------------------------------
# BE-LOOKUP-1 (Sprint 2): normalized column lookup coverage
# ---------------------------------------------------------------------------


def test_find_related_order_id_normalized_match():
    """An invoice that mentions an order number with different
    separators must still resolve via the normalized column."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database.base import Base
    from app.models import Order
    from app.services.business_extraction import InvoiceExtraction, _find_related_order_id

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as db:
        db.add(
            Order(
                document_id=900,
                order_number="PV-2026/077",
                order_number_normalized="pv2026077",
                date=__import__("datetime").date(2026, 5, 10),
                confidence=0.9,
            )
        )
        db.commit()
        extraction = InvoiceExtraction(
            document_id=901,
            invoice_number="F-1",
            supplier_name="X",
            supplier_tax_id=None,
            client_name="Y",
            date=__import__("datetime").date(2026, 5, 11),
            taxable_base=100.0,
            vat_amount=21.0,
            total_amount=121.0,
            currency="EUR",
            related_order_number="PV-2026-077",  # hyphen instead of slash
            confidence=0.9,
        )
        resolved = _find_related_order_id(db, extraction)
        assert resolved is not None
        assert resolved == 1


def test_find_related_budget_id_exact_match_tier1():
    """Exact string match on budget_number should resolve in tier 1."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database.base import Base
    from app.models import Budget
    from app.services.business_extraction import OrderExtraction, _find_related_budget_id

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as db:
        db.add(
            Budget(
                document_id=800,
                budget_number="2026/143",
                budget_number_normalized="2026143",
                date=__import__("datetime").date(2026, 5, 12),
                confidence=0.9,
            )
        )
        db.commit()
        extraction = OrderExtraction(
            document_id=801,
            order_number="P-1",
            supplier_name="X",
            client_name="Y",
            date=None,
            total_amount=10.0,
            currency="EUR",
            related_budget_number="2026/143",  # exact match
            confidence=0.9,
        )
        resolved = _find_related_budget_id(db, extraction)
        assert resolved is not None
        assert resolved == 1


def test_find_related_budget_id_python_fallback_pre_migration():
    """Tier 3 fallback: when budget_number_normalized is NULL
    (pre-migration row), the Python loop must still find the match."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database.base import Base
    from app.models import Budget
    from app.services.business_extraction import OrderExtraction, _find_related_budget_id

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as db:
        # Pre-migration row: no normalized column populated.
        b = Budget(
            document_id=700,
            budget_number="2026/143",
            budget_number_normalized=None,  # not backfilled
            date=__import__("datetime").date(2026, 5, 12),
            confidence=0.9,
        )
        db.add(b)
        db.commit()
        extraction = OrderExtraction(
            document_id=701,
            order_number="P-1",
            supplier_name="X",
            client_name="Y",
            date=None,
            total_amount=10.0,
            currency="EUR",
            related_budget_number="2026-143",  # different separator
            confidence=0.9,
        )
        resolved = _find_related_budget_id(db, extraction)
        assert resolved is not None
        assert resolved == b.id


def test_persist_sets_normalized_columns_on_budget_and_order():
    """persist_business_extraction must populate the normalized
    columns on both Budget and Order rows."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database.base import Base
    from app.models import Budget, Document, Order
    from app.services.business_extraction import persist_business_extraction

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)

    with SessionLocal() as db:
        # --- Budget ---
        doc_budget = Document(
            original_filename="presupuesto.txt",
            stored_filename="aa/presupuesto.txt",
            source_path="/data/input/presupuestos/presupuesto.txt",
            file_hash="c1" * 32,
            mime_type="text/plain",
            extension=".txt",
            file_size=10,
            document_type="presupuesto",
            status="processing",
            confidence=0.9,
        )
        db.add(doc_budget)
        db.flush()
        persist_business_extraction(
            db,
            doc_budget,
            """
            PRESUPUESTO 2026/143
            Cliente: Demo
            Fecha: 12/05/2026
            Estado: Aceptado
            Total presupuesto: 100,00 EUR
            """,
        )
        db.commit()
        budget = db.scalar(select(Budget))
        assert budget is not None
        assert budget.budget_number_normalized == "2026143"

        # --- Order referencing the budget above ---
        doc_order = Document(
            original_filename="pedido.txt",
            stored_filename="aa/pedido.txt",
            source_path="/data/input/pedidos/pedido.txt",
            file_hash="c2" * 32,
            mime_type="text/plain",
            extension=".txt",
            file_size=10,
            document_type="pedido",
            status="processing",
            confidence=0.9,
        )
        db.add(doc_order)
        db.flush()
        persist_business_extraction(
            db,
            doc_order,
            """
            Pedido PV-2026/077
            Proveedor: Herrajes Centro
            Cliente: Demo
            Fecha pedido: 14/05/2026
            Presupuesto relacionado: 2026/143
            Total pedido: 100,00 EUR
            """,
        )
        db.commit()
        order = db.scalar(select(Order))
        assert order is not None
        assert order.order_number_normalized == "pv2026077"
        assert order.related_budget_id == budget.id
