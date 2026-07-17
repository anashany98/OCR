from pathlib import Path

import httpx

from app.ocr.base import OCRResult
from app.ocr.ovisocr2 import OvisOCR2Config, OvisOCR2Engine
from app.ocr.routing import ovisocr2_eligibility, stable_ovisocr2_canary


def _engine(*, canary_percent: int) -> OvisOCR2Engine:
    return OvisOCR2Engine(
        OvisOCR2Config(
            enabled=True,
            endpoint="http://ovisocr2:8000",
            model="ATH-MaaS/OvisOCR2",
            revision="77bfe9462d1e6f8965ee6698f08ea8ede580912c",
            timeout_seconds=10,
            connect_timeout_seconds=1,
            max_tokens=100,
            max_response_bytes=10_000,
            keep_visual_regions=True,
            canary_percent=canary_percent,
        ),
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))),
    )


def test_canary_is_stable_for_the_same_document_page(tmp_path: Path):
    first = stable_ovisocr2_canary(99, 3, 25)
    assert stable_ovisocr2_canary(99, 3, 25) is first


def test_native_control_never_calls_ovis_even_with_full_canary(tmp_path: Path):
    decision = ovisocr2_eligibility(
        tmp_path / "native.png",
        baseline=OCRResult(text="texto", confidence=0.99, blocks=[]),
        content_route="native_text",
        document_id=1,
        page_number=1,
        canary_percent=100,
        tier4_primary=True,
    )
    assert decision == type(decision)(eligible=False, reason="native_control")


def test_low_quality_page_is_explainably_eligible(tmp_path: Path):
    decision = ovisocr2_eligibility(
        tmp_path / "scan.png",
        baseline=OCRResult(text="ruido", confidence=0.1, blocks=[]),
        content_route="standard_ocr",
        document_id=1,
        page_number=1,
        canary_percent=0,
        tier4_primary=False,
    )
    assert decision.eligible
    assert decision.reason == "low_ocr_confidence"


def test_engine_forces_tier4_only_for_an_eligible_stable_canary(tmp_path: Path):
    engine = _engine(canary_percent=100)
    engine.set_context(
        document_id=7,
        page_number=3,
        content_route="standard_ocr",
        baseline=OCRResult(text="legible", confidence=0.99, blocks=[]),
    )
    assert engine.should_force_tier4(tmp_path / "page.png")

    engine.set_context(
        document_id=7,
        page_number=3,
        content_route="native_text",
        baseline=OCRResult(text="legible", confidence=0.99, blocks=[]),
    )
    assert not engine.should_force_tier4(tmp_path / "page.png")
    engine.close()
