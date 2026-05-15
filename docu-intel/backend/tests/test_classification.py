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

