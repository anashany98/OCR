from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from app.ocr.base import OCRResult


def _write_test_image(path: Path, *, width: int = 420, height: int = 300) -> None:
    image = np.full((height, width, 3), 255, dtype=np.uint8)
    cv2.putText(image, "Factura 123", (25, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 2)
    cv2.line(image, (10, height - 30), (width - 10, height - 10), (40, 120, 200), 3)
    cv2.imwrite(str(path), image)


def test_preprocess_for_tesseract_binarizes_and_upscales_small_image(tmp_path: Path, monkeypatch):
    from app.ocr import preprocess

    monkeypatch.setattr(preprocess, "_detect_osd_rotation", lambda image: 0, raising=False)
    image_path = tmp_path / "scan.png"
    _write_test_image(image_path)

    output = preprocess.preprocess_for_tesseract(image_path)

    assert output != image_path
    assert output.exists()
    result = cv2.imread(str(output), cv2.IMREAD_GRAYSCALE)
    assert result is not None
    assert min(result.shape[:2]) >= 600
    unique_values = np.unique(result)
    assert set(unique_values.tolist()).issubset({0, 255})
    assert cv2.imread(str(image_path), cv2.IMREAD_COLOR) is not None


def test_preprocess_for_paddle_keeps_non_binary_image_and_upscales(tmp_path: Path, monkeypatch):
    from app.ocr import preprocess

    monkeypatch.setattr(preprocess, "_detect_osd_rotation", lambda image: 0, raising=False)
    image_path = tmp_path / "scan.png"
    _write_test_image(image_path)

    output = preprocess.preprocess_for_paddle(image_path)

    assert output != image_path
    result = cv2.imread(str(output), cv2.IMREAD_UNCHANGED)
    assert result is not None
    assert result.ndim == 3
    assert min(result.shape[:2]) >= 600
    assert len(np.unique(result.reshape(-1, result.shape[-1]), axis=0)) > 2


def test_preprocess_corrects_osd_right_angle_rotation(tmp_path: Path, monkeypatch):
    from app.ocr import preprocess

    monkeypatch.setattr(preprocess, "_detect_osd_rotation", lambda image: 90, raising=False)
    image_path = tmp_path / "wide.png"
    _write_test_image(image_path, width=1600, height=800)

    output = preprocess.preprocess_for_paddle(image_path)
    result = cv2.imread(str(output), cv2.IMREAD_UNCHANGED)

    assert result is not None
    assert result.shape[0] > result.shape[1]


def test_tesseract_extract_uses_tesseract_preprocess(monkeypatch, tmp_path: Path):
    from app.ocr import tesseract

    original = tmp_path / "original.png"
    processed = tmp_path / "processed.png"
    _write_test_image(original)
    _write_test_image(processed)
    opened: list[Path] = []

    monkeypatch.setattr(tesseract, "preprocess_for_tesseract", lambda path: processed, raising=False)
    monkeypatch.setattr(tesseract.Image, "open", lambda path: opened.append(Path(path)) or object())
    monkeypatch.setattr(
        tesseract.pytesseract,
        "image_to_data",
        lambda *args, **kwargs: {"text": [], "conf": [], "left": [], "top": [], "width": [], "height": []},
    )

    engine = object.__new__(tesseract.TesseractOCREngine)
    engine.lang = "spa+eng"
    engine.oem = 1
    engine.psm = 3

    engine.extract(original)

    assert opened == [processed]


def test_paddle_and_pp_structure_use_paddle_preprocess(monkeypatch, tmp_path: Path):
    from app.ocr import paddle, pp_structure

    original = tmp_path / "original.png"
    processed = tmp_path / "processed.png"
    _write_test_image(original)
    _write_test_image(processed)
    calls: list[Path] = []

    def fake_preprocess(path: Path) -> Path:
        calls.append(path)
        return processed

    class _PaddleModel:
        def ocr(self, path: str):
            assert Path(path) == processed
            return []

    class _Pipeline:
        def predict(self, path: str):
            assert Path(path) == processed
            return iter([])

    monkeypatch.setattr(paddle, "preprocess_for_paddle", fake_preprocess, raising=False)
    paddle_engine = object.__new__(paddle.PaddleOCREngine)
    paddle_engine.__dict__["_engine"] = _PaddleModel()
    assert paddle_engine.extract(original).engine == "paddleocr"

    monkeypatch.setattr(pp_structure, "preprocess_for_paddle", fake_preprocess, raising=False)
    pp_engine = pp_structure.PPStructureEngine(device="gpu")
    pp_engine.__dict__["_pipeline"] = _Pipeline()
    assert pp_engine.extract(original) == OCRResult(text="", confidence=None, blocks=[], engine="pp_structure")

    assert calls == [original, original]
