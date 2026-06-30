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
