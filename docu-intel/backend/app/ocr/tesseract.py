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
from app.ocr.preprocess import preprocess_adaptive
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

    def extract(self, image_path: Path) -> OCRResult:
        start = time.perf_counter()
        ocr_path = preprocess_adaptive(image_path, engine=self.name)
        try:
            image = Image.open(ocr_path)
            data = pytesseract.image_to_data(
                image,
                lang=self.lang,
                output_type=pytesseract.Output.DICT,
                config=f"--oem {self.oem} --psm {self.psm}",
            )
            tokens = []
            confidences = []
            n = len(data.get("text", []))
            for i in range(n):
                text = (data["text"][i] or "").strip()
                if not text:
                    continue
                try:
                    conf_raw = float(data["conf"][i])
                except (TypeError, ValueError):
                    conf_raw = -1.0
                if conf_raw < 0:
                    continue
                conf = conf_raw / 100.0
                try:
                    x = float(data["left"][i])
                    y = float(data["top"][i])
                    w = float(data["width"][i])
                    h = float(data["height"][i])
                except (TypeError, ValueError):
                    continue
                tokens.append({"text": text, "x": x, "y": y, "w": w, "h": h, "conf": conf})
                confidences.append(conf)

            full_text, blocks = self._group_tokens_into_lines(tokens)

            avg_conf = sum(confidences) / len(confidences) if confidences else None
            track_ocr_duration(time.perf_counter() - start)
            return OCRResult(text=full_text, confidence=avg_conf, blocks=blocks, engine=self.name)
        finally:
            if ocr_path != image_path:
                ocr_path.unlink(missing_ok=True)

    def _group_tokens_into_lines(
        self, tokens: list[dict]
    ) -> tuple[str, list[OCRBlock]]:
        """Group word-level tokens into lines by Y coordinate."""
        if not tokens:
            return "", []

        tokens.sort(key=lambda t: (t["y"], t["x"]))

        # Use median token height for line grouping threshold
        heights = [t["h"] for t in tokens if t["h"] > 0]
        if heights:
            heights.sort()
            median_h = heights[len(heights) // 2]
            y_threshold = max(median_h * 0.5, 5)
        else:
            y_threshold = 10

        lines: list[list[dict]] = []
        current_line = [tokens[0]]

        for token in tokens[1:]:
            if abs(token["y"] - current_line[0]["y"]) <= y_threshold:
                current_line.append(token)
            else:
                lines.append(current_line)
                current_line = [token]
        lines.append(current_line)

        # Build text and blocks
        text_parts = []
        blocks = []
        for line_tokens in lines:
            line_tokens.sort(key=lambda t: t["x"])
            line_text = " ".join(t["text"] for t in line_tokens)
            text_parts.append(line_text)

            x1 = min(t["x"] for t in line_tokens)
            y1 = min(t["y"] for t in line_tokens)
            x2 = max(t["x"] + t["w"] for t in line_tokens)
            y2 = max(t["y"] + t["h"] for t in line_tokens)
            avg_conf = sum(t["conf"] for t in line_tokens) / len(line_tokens)
            blocks.append(OCRBlock(
                text=line_text,
                confidence=avg_conf,
                bbox=(x1, y1, x2, y2),
            ))

        return "\n".join(text_parts), blocks


__all__ = ["TesseractOCREngine"]
