from app.services.classification import classify_document


def test_classifies_budget_from_filename_folder_and_text():
    result = classify_document(
        filename="Presupuesto_2026_143.pdf",
        source_path="/data/input/presupuestos/Presupuesto_2026_143.pdf",
        text="Cliente ACME. Total presupuesto 1245,60 EUR. Validez 30 dias.",
    )

    assert result.document_type == "presupuesto"
    assert result.confidence >= 0.8


def test_classifies_plan_from_folder_and_keywords():
    result = classify_document(
        filename="obra-x-planta.pdf",
        source_path="/data/input/planos/obra-x-planta.pdf",
        text="Escala 1:50. Planta baja. Salon 24 m2. Cotas principales.",
    )

    assert result.document_type == "plano"
    assert result.confidence >= 0.8


def test_image_inside_planos_folder_stays_image_without_plan_signals():
    result = classify_document(
        filename="foto_sofa.jpg",
        source_path="/data/input/planos/foto_sofa.jpg",
        text="Foto de sofa tapizado y mesa auxiliar sin escala ni cotas tecnicas.",
    )

    assert result.document_type == "imagen"


def test_image_inside_planos_folder_with_plan_filename_can_be_plan():
    result = classify_document(
        filename="plano_planta_baja.jpg",
        source_path="/data/input/planos/plano_planta_baja.jpg",
        text="",
    )

    assert result.document_type == "plano"


def test_planos_folder_pdf_needs_real_plan_signal():
    result = classify_document(
        filename="catalogo_muebles.pdf",
        source_path="/data/input/planos/catalogo_muebles.pdf",
        text="Catalogo de muebles para salon con medidas de ancho y alto.",
    )

    assert result.document_type != "plano"

