from pathlib import Path

from app.ocr.base import OCRResult
from app.services import document_processing_core


class _FakeEngine:
    name = "fake"

    def extract(self, image_path: Path) -> OCRResult:
        return OCRResult(text="ok", confidence=1.0, blocks=[], engine=self.name)


def test_engine_factory_callable_provider_is_resolved_to_engine(monkeypatch):
    # Mirrors the cascading factory shape: factory -> provider function ->
    # singleton engine. The page-reprocess path must not retain the provider.
    monkeypatch.setattr(
        document_processing_core,
        "_get_effective_ocr_engine_class",
        lambda: (lambda: _FakeEngine()),
    )

    engine = document_processing_core._instantiate_effective_ocr_engine()

    assert engine.name == "fake"
    assert engine.extract(Path("ignored.png")).text == "ok"
