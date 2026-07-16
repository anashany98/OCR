from app.ocr.base import OCRResult
from app.services.ocr_decision import decide_ocr_result


def _result(text: str, confidence: float | None, engine: str = "test") -> OCRResult:
    return OCRResult(text=text, confidence=confidence, blocks=[], engine=engine)


def test_accepts_clean_high_confidence_ocr():
    decision = decide_ocr_result(_result("Factura 2025 ACME total 1200 euros " * 8, 0.95))
    assert decision.decision == "auto_accepted"
    assert decision.calibrated_confidence >= 0.70


def test_unknown_vlm_confidence_requires_review_without_supporting_evidence():
    decision = decide_ocr_result(_result("Nota manuscrita puerta ochenta centimetros " * 8, None, "dots_mocr"))
    assert decision.decision == "review_required"
    assert "derived_confidence" in decision.reasons


def test_conflicting_numbers_require_review_when_baseline_is_reliable():
    baseline = _result("Factura total 1200 euros " * 12, 0.95)
    candidate = _result("Factura total 3200 euros " * 12, 0.95, "dots_mocr")
    decision = decide_ocr_result(candidate, baseline=baseline)
    assert decision.decision == "review_required"
    assert "numeric_conflict" in decision.reasons


def test_empty_result_requires_review():
    decision = decide_ocr_result(_result("", None, "dots_mocr"))
    assert decision.decision == "review_required"
    assert "empty_text" in decision.reasons
