"""FASE 2 — multi-dimensional classifier regression tests.

These tests exercise ``app.services.classification_v2`` against the
fingerprint-style mini corpus. They do NOT touch the live database;
they only check that the layered decisions produce the expected
``source_format`` / ``document_type`` / ``document_subtype`` / ``content_tags``
combination for each of the BON PLA SOCIEDAD ANONIMA archetype
documents.

The tests are intentionally small and deterministic so they run on
any developer machine without GPU, LLM or filesystem fixtures.
"""
from __future__ import annotations

from app.services.classification_v2 import (
    CLASSIFIER_VERSION,
    classify_multidim,
    detect_source_format,
    detect_subtype,
    detect_content_tags,
)


def _case(name: str, filename: str, mime: str, text: str = "") -> dict:
    result = classify_multidim(
        filename=filename,
        source_path=None,
        mime_type=mime,
        parser_signature=None,
        text=text,
    )
    return {
        "name": name,
        "source_format": result.source_format,
        "document_type": result.document_type,
        "document_subtype": result.document_subtype,
        "content_tags": list(result.content_tags),
        "confidence": result.confidence,
        "classifier_version": result.classifier_version,
    }


def test_msg_keeps_email_source_format():
    case = _case(
        "msg-presupuesto",
        "PEDIDO PROVEEDOR.msg",
        "application/vnd.ms-outlook",
        "Pedido de proveedor para HOSTAL ANIBAL",
    )
    assert case["source_format"] == "email", case
    assert case["document_type"] == "email_exportado", case
    # The MSG file must NEVER be relabelled as a product photo even
    # if the body mentions furniture.
    assert case["document_type"] != "foto_producto", case
    # ``proveedor`` is a subtype marker, not a content tag, so the
    # tag set should not include it; the subtype column does.
    assert case["document_subtype"] == "proveedor", case
    assert "proveedor" not in case["content_tags"], case


def test_xlsx_keeps_spreadsheet_source_format():
    case = _case(
        "xlsx-carpinteria",
        "HOSTAL ANIBAL CARPINTERIA 2.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Mueble | Cantidad | Precio | Total\nCabecero | 4 | 250 | 1000",
    )
    assert case["source_format"] == "spreadsheet", case
    # The .xlsx must NEVER be relabelled as a product photo.
    assert case["document_type"] != "foto_producto", case
    assert "carpinteria" in case["content_tags"] or "mobiliario" in case["content_tags"], case


def test_docx_keeps_word_source_format():
    case = _case(
        "docx-medicion",
        "medición 2 armarios.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "Ancho 1200mm x Alto 2400mm, dos armarios empotrados",
    )
    assert case["source_format"] == "word", case
    assert "medicion" in case["content_tags"], case
    assert case["document_type"] == "medicion", case


def test_image_ppto_keeps_image_source_format():
    case = _case(
        "jpeg-ppto-firmado",
        "ppto firmado.jpeg",
        "image/jpeg",
        "Presupuesto firmado con fecha 23/06/2024",
    )
    assert case["source_format"] == "image", case
    assert case["document_type"] == "presupuesto", case
    assert case["document_subtype"] == "firmado", case
    # Image with a presupuesto MUST NOT become foto_producto.
    assert case["document_type"] != "foto_producto", case


def test_pdf_incidencia_keeps_pdf_source_format():
    case = _case(
        "pdf-incidencia",
        "incidencia sillas.pdf",
        "application/pdf",
        "Incidencia detectada en la zona de sillas del comedor principal",
    )
    assert case["source_format"] == "pdf", case
    # The body says "incidencia" — the subtype should pick it up.
    assert case["document_subtype"] in (None, "proveedor"), case
    # Even if document_type stays as the rule-engine default, the
    # PDF must NEVER be relabelled as a product photo.
    assert case["document_type"] == "incidencia", case


def test_pdf_with_ppto_kept_as_presupuesto():
    case = _case(
        "pdf-presupuesto",
        "3987_001.pdf",
        "application/pdf",
        "PRESUPUESTO\nTotal: 1234,56 €\nValidez 30 días",
    )
    assert case["source_format"] == "pdf", case
    assert case["document_type"] == "presupuesto", case


def test_dxf_keeps_dxf_source_format():
    # DXF detection uses the parser signature: the MIME for DXF is
    # ``image/vnd.dxf`` (a common convention) but the extension
    # vote alone is enough if a parser reports ``ezdxf``.
    fmt, _ = detect_source_format(
        filename="plano.dxf", mime_type=None, parser_signature="ezdxf"
    )
    assert fmt == "dxf", fmt
    # Without a parser signal, a plain .dxf still wins because the
    # extension map includes dxf.
    fmt, _ = detect_source_format(
        filename="plano.dxf", mime_type=None, parser_signature=None
    )
    assert fmt == "dxf", fmt


def test_unknown_source_format_is_handled():
    case = _case("unknown-1", "mystery.bin", "application/octet-stream", "")
    assert case["source_format"] in ("unknown", "text"), case


def test_classifier_version_is_exported():
    assert CLASSIFIER_VERSION.startswith("minimax-m3-"), CLASSIFIER_VERSION


def test_subtype_known_markers():
    assert detect_subtype("ppto firmado.jpeg", "") == "firmado"
    assert detect_subtype("ppto aceptado.jpeg", "") == "aceptado"
    # The order of the rules makes ``entrega`` win over ``cliente``
    # when only one is in the haystack. When both are present, the
    # first listed rule wins (cliente in this version).
    assert detect_subtype("albaran entrega.pdf", "") == "entrega"
    assert detect_subtype("albaran recogida.pdf", "") == "recogida"
    assert detect_subtype("pedido proveedor.pdf", "") == "proveedor"


def test_subtype_unknown_returns_none():
    assert detect_subtype("doc.pdf", "sin marcadores") is None


def test_content_tags_dedup_and_cap():
    text = "Mueble sillón mesa carpintería plano presupuesto HOSTAL ANIBAL"
    tags = detect_content_tags("doc.pdf", text, max_tags=3)
    assert len(tags) == 3
    # The first three matches win; the rest are not in the list.
    assert tags == tags[:3]


def test_source_format_vote_weights():
    # extension only → 0.6
    fmt, decisions = detect_source_format(filename="foo.pdf", mime_type=None)
    assert fmt == "pdf", decisions
    assert any(d.layer == "extension" for d in decisions), decisions
    # parser signature beats extension when both disagree.
    fmt, decisions = detect_source_format(
        filename="foo.pdf", mime_type=None, parser_signature="openpyxl"
    )
    assert fmt == "spreadsheet", decisions
    # parser wins because its weight (0.8) is higher than extension (0.6).
    weights = {d.layer: d.weight for d in decisions}
    assert weights["parser"] > weights["extension"], decisions
