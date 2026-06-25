"""Deterministic smoke test for the cascade OCR factory.

Three scenarios, each clearly biased so we can see the cascade make the
expected call:

  1. EASY:  a long, crisp, single-line string.  Tesseract should win.
  2. NOISE: a noisy image with a faint watermark.  We print both
            engines' raw output so the cascade's choice is auditable.
  3. BLANK: a white image.  Both engines return nothing; the cascade
            should keep the primary (engine.name == "tesseract",
            text == "") and not raise.

Run inside the backend container::

    docker compose cp backend/scripts/cascade_smoke.py backend:/tmp/
    docker compose exec -T backend bash -lc "PYTHONPATH=/app python /tmp/cascade_smoke.py"
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.ocr.base import OCRResult
from app.ocr.cascading import CascadingOCREngine
from app.ocr.factory import get_ocr_engine_class
from app.ocr.paddle import PaddleOCREngine
from app.ocr.tesseract import TesseractOCREngine


def _font() -> ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, 28)
        except OSError:
            continue
    return ImageFont.load_default()


def _make_easy(path: Path) -> None:
    """A long, crisp, high-contrast line of text.  Tesseract should eat this."""
    img = Image.new("RGB", (1400, 100), "white")
    draw = ImageDraw.Draw(img)
    draw.text(
        (20, 30),
        "CASCADE OCR SMOKE TEST 12345 - Esta es una linea de prueba muy larga "
        "para que Tesseract la procese sin problemas",
        fill="black",
        font=_font(),
    )
    img.save(path)


def _make_noise(path: Path) -> None:
    """A faint watermark over a noisy background."""
    rng = random.Random(42)
    img = Image.new("RGB", (1200, 100), "white")
    draw = ImageDraw.Draw(img)
    for _ in range(2500):
        x = rng.randint(0, img.width - 1)
        y = rng.randint(0, img.height - 1)
        draw.point((x, y), fill=rng.choice(["black", "gray", "lightgray"]))
    draw.text(
        (20, 30),
        "Documento confidencial 2026 - Documento confidencial 2026 - "
        "Documento confidencial 2026 - Documento confidencial 2026",
        fill=(120, 120, 120),
        font=_font(),
    )
    img.save(path)


def _summarise(label: str, result: OCRResult) -> None:
    chars = len(result.text.strip())
    print(f"--- {label} ---")
    print(f"  engine:    {result.engine}")
    print(f"  chars:     {chars}")
    print(f"  conf:      {result.confidence}")
    print(f"  blocks:    {len(result.blocks)}")
    print(f"  preview:   {result.text[:80]!r}")


def main() -> int:
    cls = get_ocr_engine_class()
    cascade: CascadingOCREngine = cls()  # type: ignore[assignment]
    print(f"cascade class:    {type(cascade).__name__}")
    print(f"primary:          {type(cascade.primary).__name__}")
    print(f"fallback:         {type(cascade.fallback).__name__}")
    print(f"min_chars:        {cascade.min_chars}")
    print(f"min_confidence:   {cascade.min_confidence}")

    easy = Path("/tmp/cascade_easy.png")
    noise = Path("/tmp/cascade_noise.png")
    blank = Path("/tmp/cascade_blank.png")
    _make_easy(easy)
    _make_noise(noise)
    Image.new("RGB", (400, 100), "white").save(blank)

    # ---- Scenario 1: easy text -> Tesseract wins, no escalation. ----
    cascade._name = ""
    result = cascade.extract(easy)
    _summarise("EASY (expect tesseract)", result)
    assert result.engine == "tesseract", f"expected tesseract, got {result.engine}"
    assert len(result.text.strip()) >= 30, "easy image should yield >=30 chars"

    # ---- Scenario 2: noisy text -> run each engine raw, then the cascade. ----
    tess: TesseractOCREngine = cascade.primary  # type: ignore[assignment]
    padd: PaddleOCREngine = cascade.fallback  # type: ignore[assignment]
    tess_result = tess.extract(noise)
    padd_result = padd.extract(noise)
    _summarise("NOISE / tesseract raw", tess_result)
    _summarise("NOISE / paddle raw", padd_result)

    cascade._name = ""
    result = cascade.extract(noise)
    _summarise("NOISE (cascade result)", result)

    # ---- Scenario 3: blank -> no engine crashes, text empty. ----
    cascade._name = ""
    result = cascade.extract(blank)
    _summarise("BLANK (expect tesseract, empty)", result)
    assert result.text.strip() == "", "blank image should yield empty text"
    assert result.engine == "tesseract", f"blank cascade should keep primary, got {result.engine}"

    print("\nALL SCENARIOS PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
