"""Tesseract 5 OCR engine.

CPU only, no GPU dependency. ~1.5 GB lighter Docker image than PaddleOCR.
Returns word-level blocks with bounding boxes and confidences (0-1 scale).

Install the tesseract binary plus the language packs in the container::

    apt-get install -y tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng

For Spanish+English layouts (invoices, budgets, planos) the default
``spa+eng`` language set covers the vast majority of characters. The OEM
flag is locked to LSTM (``oem=1``) which is the Tesseract 5 default and
the only engine worth using. PSM=3 ("fully automatic page segmentation")
is the right default for free-form scans; per-page overrides can be set
via the ``TESSERACT_PSM`` env var.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import ClassVar

import pytesseract
from PIL import Image

from app.ocr.base import OCRBlock, OCRResult
from app.ocr.preprocess import preprocess_for_tesseract
from app.services.metrics import track_ocr_duration


class TesseractOCREngine:
    """Tesseract 5 OCR engine via the ``pytesseract`` Python binding.

    The engine is stateless: every call to :meth:`extract` opens the
    image, runs the tesseract binary, and returns word-level blocks. No
    model warm-up is needed (the binary loads in a few ms).
    """

    name: ClassVar[str] = "tesseract"

    def __init__(self, lang: str = "spa+eng", oem: int = 1, psm: int = 3) -> None:
        self.lang = lang
        self.oem = oem
        self.psm = psm
        # Fail fast at construction if the binary is missing so workers
        # don't get stuck retrying with a confusing PIL/Tesseract error.
        try:
            pytesseract.get_tesseract_version()
        except pytesseract.TesseractNotFoundError as exc:
            raise RuntimeError(
                "tesseract binary not found in PATH. "
                "Install with: "
                "apt-get install -y tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng"
            ) from exc

    def extract(
        self,
        image_path: Path,
        *,
        language: str | None = None,
    ) -> OCRResult:
        start = time.perf_counter()
        ocr_path = preprocess_for_tesseract(image_path)
        image = Image.open(ocr_path)
        # ``image_to_data`` returns one row per detected token plus its
        # bounding box and a 0-100 confidence. We turn the confidence
        # into 0-1 to match what PaddleOCR returned and what the
        # ``DocumentBlock.confidence`` column expects.
        data = pytesseract.image_to_data(
            image,
            lang=self.lang,
            output_type=pytesseract.Output.DICT,
            config=f"--oem {self.oem} --psm {self.psm}",
        )
        blocks: list[OCRBlock] = []
        confidences: list[float] = []
        n = len(data.get("text", []))
        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            try:
                conf_raw = float(data["conf"][i])
            except (TypeError, ValueError):
                conf_raw = -1.0
            # Tesseract uses -1 to mark rows it could not classify (eg
            # page-number regions in PSM=11). Drop them so they don't
            # pollute the average confidence.
            if conf_raw < 0:
                continue
            conf = conf_raw / 100.0
            try:
                x = float(data["left"][i])
                y = float(data["top"][i])
                w = float(data["width"][i])
                h = float(data["height"][i])
                bbox: tuple[float, float, float, float] | None = (x, y, x + w, y + h)
            except (TypeError, ValueError):
                bbox = None
            blocks.append(OCRBlock(text=text, confidence=conf, bbox=bbox))
            confidences.append(conf)
        full_text = "\n".join(b.text for b in blocks if b.text)
        avg_conf = sum(confidences) / len(confidences) if confidences else None
        track_ocr_duration(time.perf_counter() - start)
        return OCRResult(text=full_text, confidence=avg_conf, blocks=blocks, engine=self.name)


__all__ = ["TesseractOCREngine"]
