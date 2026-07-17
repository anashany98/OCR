from pathlib import Path

from app.parsers.content_router import ContentRoute, _is_likely_plan, classify_content


def test_image_in_planos_folder_without_plan_signals_routes_as_photo():
    result = classify_content(Path("sofa.jpg"), folder_hint="planos")

    assert result.route == ContentRoute.INTERIOR_DESIGN
    assert result.reason == "image_no_text_likely_photo"


def test_image_in_planos_folder_with_furniture_text_routes_as_interior():
    result = classify_content(
        Path("mueble_salon.jpg"),
        extracted_text="Foto de sofa tapizado con mesa auxiliar y medidas de ancho",
        folder_hint="planos",
    )

    assert result.route == ContentRoute.INTERIOR_DESIGN


def test_pdf_with_embedded_furniture_text_is_not_forced_to_plan():
    result = classify_content(
        Path("plantilla_muebles.pdf"),
        extracted_text="Catalogo de muebles para salon. Sofa, mesa, sillas y tapizado.",
        folder_hint="planos",
    )

    assert result.route == ContentRoute.INTERIOR_DESIGN


def test_pdf_with_scale_and_plan_terms_routes_to_plan():
    result = classify_content(
        Path("reforma.pdf"),
        extracted_text="Escala 1:100. Plano planta baja. Cotas generales 3,50 m.",
        folder_hint="planos",
    )

    assert result.route == ContentRoute.PLAN_OCR


def test_plan_detector_does_not_treat_furniture_measurements_as_plan():
    is_plan, _, reason = _is_likely_plan(
        "Mueble salon ancho 2,40 m largo 1,20 m alto 80 cm tapizado tela"
    )

    assert is_plan is False
    assert reason == "no_plan_signals"


# ---------------------------------------------------------------------------
# Handwritten-document routing (regression 2026-07-16).
#
# Hojas de confección, órdenes de trabajo, croquis and measurements
# are filled by hand in this project. Tesseract / PaddleOCR return
# empty or corrupted text on them, so the standard cascade wastes
# time and produces empty bodies that break RAG. The router must
# flag them as ``vlm_ocr`` so ``CascadingOCREngine`` jumps straight
# to the OvisOCR2 tier.
# ---------------------------------------------------------------------------


def test_hoja_de_confeccion_pdf_routes_to_vlm_ocr():
    result = classify_content(Path("hoja de confeccion sombrillas erroneas beige.pdf"))
    assert result.route == ContentRoute.VLM_OCR
    assert "handwritten" in result.reason


def test_hoja_de_confeccion_image_routes_to_vlm_ocr():
    result = classify_content(Path("hoja de confeccion III.png"))
    assert result.route == ContentRoute.VLM_OCR


def test_orden_de_trabajo_routes_to_vlm_ocr():
    result = classify_content(Path("OT 250102 cliente hotel.pdf"))
    assert result.route == ContentRoute.VLM_OCR


def test_croquis_with_measurements_routes_to_vlm_ocr_not_interior():
    """``croquis`` is the canonical handwritten drawing type. The
    previous behaviour returned ``INTERIOR_DESIGN`` which SKIPS OCR
    entirely and returns an empty body, breaking RAG."""
    result = classify_content(Path("croquis medidas cocina.pdf"))
    assert result.route == ContentRoute.VLM_OCR


def test_medicion_pdf_routes_to_vlm_ocr():
    result = classify_content(Path("Medición 2 armarios hotel lobby.pdf"))
    assert result.route == ContentRoute.VLM_OCR


def test_incidencia_routes_to_vlm_ocr():
    result = classify_content(Path("incidencia silla lobby 2025-04-22.pdf"))
    assert result.route == ContentRoute.VLM_OCR


def test_incidencia_con_imagen_extension_also_routes_to_vlm():
    """Extension is irrelevant — the filename signal must win."""
    result = classify_content(Path("incidencia sala.jpg"))
    assert result.route == ContentRoute.VLM_OCR


def test_typed_pdf_with_no_handwritten_signal_stays_standard_ocr():
    """Sanity check: a quote or invoice that does NOT match any
    handwritten keyword keeps the default route."""
    result = classify_content(
        Path("Presupuesto 1-250544.pdf"),
        extracted_text="Cliente ACME. Total 1245 EUR. Validez 30 dias.",
    )
    assert result.route == ContentRoute.STANDARD_OCR


def test_bare_word_hoja_alone_does_not_force_vlm():
    """The multi-word check must not be satisfied by a single token.
    ``hoja.pdf`` is ambiguous and should not auto-route to VLM."""
    result = classify_content(Path("hoja.pdf"))
    # Falls through to the default branch (standard_ocr) — the
    # router is intentionally conservative on isolated tokens.
    assert result.route != ContentRoute.VLM_OCR
