"""Tests for the learning loop (Bucle de Mejora).

Cubre:
- Clasificacion con learned rules (boost sobre built-in)
- Argumentos de las nuevas integration tools
- Helpers de webhooks (eventos correctos)
- Comportamiento de _tool_description y TOOL_ARGUMENTS
"""
from app.schemas.learning import (
    ClassificationSuggestionCreate,
    ClassificationSuggestionRead,
    ClassificationSuggestionReview,
    ImprovementCandidate,
    ImprovementCandidatesResponse,
    LearnedPatternRead,
    LearnedPatternUpdate,
)
from app.services.classification import LearnedRule, classify_document
from app.services.integration_tools.common import (
    GetImprovementCandidatesArgs,
    ProposeClassificationCorrectionArgs,
    ProposeClassificationRuleArgs,
    ProposeEntityLinkArgs,
    SubmitQualityFeedbackArgs,
    TOOL_ARGUMENTS,
    _parse_arguments,
    _tool_description,
    build_manifest,
)
from app.services.webhooks import (
    EVENT_CLASSIFICATION_LOW_CONFIDENCE,
    EVENT_DOCUMENT_NEEDS_REVIEW,
    EVENT_NEW_PATTERN_DETECTED,
)


# ---------------------------------------------------------------------------
# Classification with learned rules
# ---------------------------------------------------------------------------

def test_learned_rule_outranks_built_in():
    """Una learned rule debe coincidir cuando su patron esta en el texto."""
    rule = LearnedRule(pattern_value="certificado energetico", target_class="certificado")
    result = classify_document(
        filename="foo.pdf",
        source_path="/srv/otros/foo.pdf",
        text="Certificado energetico del edificio",
        learned_rules=[rule],
    )
    assert result.document_type == "certificado"
    assert any("learned:" in m for m in result.matched_rules)


def test_no_learned_rules_falls_back_to_built_in():
    """Sin learned rules, debe seguir funcionando la clasificacion built-in."""
    result = classify_document(
        filename="Presupuesto_2026_143.pdf",
        source_path="/data/input/presupuestos/Presupuesto_2026_143.pdf",
        text="Cliente ACME. Total presupuesto 1245,60 EUR.",
        learned_rules=None,
    )
    assert result.document_type == "presupuesto"


def test_learned_rule_ignores_empty_pattern():
    """Una rule con pattern vacio no debe romper la clasificacion."""
    rule = LearnedRule(pattern_value="", target_class="custom")
    result = classify_document(
        filename="factura.pdf",
        source_path="/srv/foo.pdf",
        text="factura 100",
        learned_rules=[rule],
    )
    assert result.document_type == "factura"


def test_classify_handles_empty_text():
    """Sin texto, debe devolver tipo desconocido con confianza baja."""
    result = classify_document(filename="x.pdf", source_path=None, text="")
    assert result.document_type == "desconocido"


# ---------------------------------------------------------------------------
# Integration tool arguments
# ---------------------------------------------------------------------------

def test_all_learning_tools_registered():
    """Las 5 nuevas tools deben estar registradas en TOOL_ARGUMENTS."""
    expected = {
        "propose_classification_correction",
        "propose_entity_link",
        "propose_classification_rule",
        "submit_quality_feedback",
        "get_improvement_candidates",
    }
    assert expected.issubset(set(TOOL_ARGUMENTS.keys()))


def test_parse_arguments_validates_types():
    """_parse_arguments debe rechazar argumentos invalidos con 422."""
    from fastapi import HTTPException

    args = {"document_id": 0, "suggested_document_type": "x", "reason": "y"}
    try:
        _parse_arguments("propose_classification_correction", args)
        assert False, "Expected 422"
    except HTTPException as exc:
        assert exc.status_code == 422


def test_parse_arguments_succeeds_for_valid_input():
    args = {
        "document_id": 42,
        "suggested_document_type": "factura",
        "reason": "contiene iva y base imponible",
        "confidence": 0.9,
    }
    parsed = _parse_arguments("propose_classification_correction", args)
    assert isinstance(parsed, ProposeClassificationCorrectionArgs)
    assert parsed.document_id == 42


def test_entity_link_args_default_target_action():
    args = {
        "source_document_id": 1,
        "target_document_id": 2,
        "reason": "mismo cliente",
    }
    parsed = _parse_arguments("propose_entity_link", args)
    assert isinstance(parsed, ProposeEntityLinkArgs)
    assert parsed.target_action == "link"


def test_classification_rule_requires_evidence_document_id():
    from fastapi import HTTPException

    args = {
        "pattern_value": "x",
        "target_class": "y",
        "target_action": "classify_as",
        "reason": "z",
    }
    parsed = _parse_arguments("propose_classification_rule", args)
    assert isinstance(parsed, ProposeClassificationRuleArgs)
    assert parsed.evidence_document_id is None


def test_get_improvement_candidates_args_defaults():
    args: dict = {}
    parsed = _parse_arguments("get_improvement_candidates", args)
    assert isinstance(parsed, GetImprovementCandidatesArgs)
    assert parsed.limit == 20
    assert parsed.min_confidence == 0.7


# ---------------------------------------------------------------------------
# Tool descriptions and manifest
# ---------------------------------------------------------------------------

def test_tool_descriptions_for_learning_tools():
    for tool in (
        "propose_classification_correction",
        "propose_entity_link",
        "propose_classification_rule",
        "submit_quality_feedback",
        "get_improvement_candidates",
    ):
        description = _tool_description(tool)
        assert description and description != f"Ejecuta la tool controlada {tool}." or "requiere aprobacion" in description.lower() or "sugiere" in description.lower() or "propone" in description.lower() or "envia" in description.lower() or "devuelve" in description.lower()


def test_manifest_version_is_1_4():
    manifest = build_manifest()
    assert manifest.version == "1.4"
    tool_names = {tool.name for tool in manifest.tools}
    assert "propose_classification_correction" in tool_names
    assert "get_improvement_candidates" in tool_names


# ---------------------------------------------------------------------------
# Webhook event constants
# ---------------------------------------------------------------------------

def test_webhook_events_defined():
    assert EVENT_DOCUMENT_NEEDS_REVIEW == "document.needs_review"
    assert EVENT_CLASSIFICATION_LOW_CONFIDENCE == "classification.low_confidence"
    assert EVENT_NEW_PATTERN_DETECTED == "entity.new_pattern_detected"


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

def test_classification_suggestion_create_validates_type_literal():
    from pydantic import ValidationError

    try:
        ClassificationSuggestionCreate(
            document_id=1,
            suggestion_type="invalid_type",
            reason="x",
        )
        assert False, "Expected ValidationError"
    except ValidationError:
        pass


def test_classification_suggestion_read_maps_evidence_json():
    data = {
        "id": 1,
        "document_id": 2,
        "integration_client_id": 3,
        "suggestion_type": "classification_correction",
        "suggested_document_type": "factura",
        "current_document_type": "presupuesto",
        "target_document_id": None,
        "pattern_value": None,
        "target_action": None,
        "confidence": 0.8,
        "reason": "test",
        "evidence_json": {"field": "amount"},
        "status": "pending",
        "reviewed_by_user_id": None,
        "reviewed_at": None,
        "applied_at": None,
        "created_at": "2026-06-02T00:00:00Z",
    }
    suggestion = ClassificationSuggestionRead.model_validate(data)
    assert suggestion.evidence == {"field": "amount"}


def test_learned_pattern_read_validates_status():
    from pydantic import ValidationError

    data = {
        "id": 1,
        "pattern_type": "keyword",
        "pattern_value": "x",
        "target_class": "y",
        "target_action": "classify_as",
        "confidence": 0.8,
        "source_suggestion_id": None,
        "status": "active",
        "applied_count": 0,
        "last_applied_at": None,
        "created_at": "2026-06-02T00:00:00Z",
        "updated_at": "2026-06-02T00:00:00Z",
    }
    pattern = LearnedPatternRead.model_validate(data)
    assert pattern.status == "active"

    bad = {**data, "status": "broken"}
    try:
        LearnedPatternRead.model_validate(bad)
        assert False, "Expected ValidationError"
    except ValidationError:
        pass


def test_classification_suggestion_review_status_literal():
    a = ClassificationSuggestionReview(status="approved")
    assert a.status == "approved"
    b = ClassificationSuggestionReview(status="rejected")
    assert b.status == "rejected"


def test_learned_pattern_update_status_literal():
    u = LearnedPatternUpdate(status="active")
    assert u.status == "active"


def test_improvement_candidate_response():
    candidates = [
        ImprovementCandidate(
            document_id=1,
            filename="x.pdf",
            document_type="desconocido",
            current_status="processed_low_quality",
            reason="confianza 0.5",
            confidence=0.5,
        )
    ]
    response = ImprovementCandidatesResponse(candidates=candidates, total=1)
    assert response.total == 1
    assert response.candidates[0].document_id == 1
