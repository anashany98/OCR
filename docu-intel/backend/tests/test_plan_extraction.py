from app.services.plan_extraction import extract_plan


def test_extracts_scale_dimensions_and_rooms_from_plan_text():
    text = """
    Proyecto: Reforma Local Centro
    Plano planta baja
    Escala 1:50
    Salon 24,50 m2
    Cocina 10 m²
    Cota general 3,50 m
    Pasillo 250 cm
    """

    result = extract_plan(document_id=12, text=text, document_confidence=0.88)

    assert result.plan is not None
    assert result.plan.project_name == "Reforma Local Centro"
    assert result.plan.scale_text == "1:50"
    assert result.plan.scale_ratio == 50.0
    assert result.plan.has_valid_scale is True
    assert result.rooms[0].name == "Salon"
    assert result.rooms[0].area_m2 == 24.5
    assert result.rooms[0].source == "ocr_text"
    assert result.rooms[0].needs_review is False
    assert any(dimension.raw_text == "3,50 m" and dimension.value_m == 3.5 for dimension in result.dimensions)
    assert any(dimension.raw_text == "250 cm" and dimension.value_m == 2.5 for dimension in result.dimensions)
    assert result.needs_review is False


def test_does_not_mark_plan_as_measurable_without_valid_scale_or_text_dimensions():
    text = """
    Plano planta primera
    Salon principal
    Dormitorio
    Sin escala
    """

    result = extract_plan(document_id=13, text=text, document_confidence=0.7)

    assert result.plan is not None
    assert result.plan.has_valid_scale is False
    assert result.plan.scale_ratio is None
    assert result.dimensions == []
    assert result.rooms == []
    assert result.needs_review is True
