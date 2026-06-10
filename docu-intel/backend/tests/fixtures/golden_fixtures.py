"""Synthetic golden fixtures for OCR regression testing.

Real customer PDFs cannot be checked in (privacy + size), so the
golden set is built from a few handwritten text templates that
each scenario in :class:`GoldenCase` renders to a PNG with a
known DPI. The PNGs are deterministic and tiny (a few KB), which
keeps the regression test self-contained and fast.

The fixtures live next to this module so the regression test
(:mod:`tests.test_ocr_golden`) can build the PNGs once at the
start of a session and reuse them across tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

# PIL is optional in the test environment; if it's missing we
# simply skip the test cases that need to render fixtures.
try:
    from PIL import Image, ImageDraw, ImageFont
except ModuleNotFoundError:  # pragma: no cover - exercised in CI
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]


FIXTURE_DIR = Path(__file__).resolve().parent / "golden"


@dataclass(frozen=True)
class GoldenCase:
    """One regression case: a rendered PNG plus the expected lines."""

    name: str
    lines: tuple[str, ...]
    # Tokens that *must* appear in the OCR output for the case
    # to pass. We tokenise on whitespace and lowercase so casing
    # and punctuation do not affect the check.
    must_contain: tuple[str, ...]
    # Tokens that *must not* appear in the OCR output (e.g.
    # garbage from noise). Optional, defaults to empty.
    must_not_contain: tuple[str, ...] = ()


# A small but representative golden set. Each case is one of the
# document types the agent already routes on (invoice, budget,
# order, plan, albaran). The text uses only ASCII so the tests
# run with the lightweight Tesseract-only engine in CI.
GOLDEN_CASES: tuple[GoldenCase, ...] = (
    GoldenCase(
        name="invoice_simple",
        lines=(
            "FACTURA 2024/0001",
            "Proveedor: ACME S.L.",
            "Cliente: MELIA HOTELS",
            "Base imponible: 1000.00",
            "IVA 21%: 210.00",
            "Total: 1210.00 EUR",
        ),
        must_contain=(
            "factura",
            "2024/0001",
            "acme",
            "melia",
            "1000.00",
            "1210.00",
        ),
    ),
    GoldenCase(
        name="budget_accepted",
        lines=(
            "PRESUPUESTO 2025/0142",
            "Cliente: HOTEL SOL",
            "Estado: ACEPTADO",
            "Importe: 5400.50",
        ),
        must_contain=(
            "presupuesto",
            "2025/0142",
            "hotel",
            "sol",
            "aceptado",
            "5400.50",
        ),
    ),
    GoldenCase(
        name="order_pending",
        lines=(
            "PEDIDO P-2025-0099",
            "Proveedor: BRICOMART",
            "Estado: PENDIENTE",
            "Total: 320.00",
        ),
        must_contain=(
            "pedido",
            "p-2025-0099",
            "bricomart",
            "pendiente",
            "320.00",
        ),
    ),
    GoldenCase(
        name="plan_caption",
        lines=(
            "PLANTA BAJA",
            "Salon 20.50 m2",
            "Cocina 12.30 m2",
            "Bano 4.80 m2",
        ),
        must_contain=(
            "planta",
            "salon",
            "cocina",
            "bano",
            "20.50",
            "12.30",
            "4.80",
        ),
    ),
    GoldenCase(
        name="albaran_signed",
        lines=(
            "ALBARAN A-2025-0007",
            "Fecha: 2025-06-10",
            "Receptor: J. PEREZ",
            "Firma: [signed]",
        ),
        must_contain=(
            "albaran",
            "a-2025-0007",
            "2025-06-10",
            "perez",
        ),
    ),
)


def _font(size: int = 24):
    """Return a small sans-serif font that ships with PIL.

    Falls back to the default bitmap font when no TTF is
    available, which is good enough for OCR smoke testing."""
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size=size)
    except (OSError, IOError):
        return ImageFont.load_default()


def _render_case(case: GoldenCase, target: Path) -> None:
    """Render ``case.lines`` to a 600x800 PNG with high contrast.

    The renderer uses a white background and black text so the
    noise-free reference matches what Tesseract handles best in
    CPU mode. Each line gets 40px of vertical space and starts
    at 60px from the top."""
    if Image is None:
        raise RuntimeError("Pillow is required to render golden fixtures")

    image = Image.new("L", (600, 800), color=255)
    draw = ImageDraw.Draw(image)
    font = _font()
    y = 60
    for line in case.lines:
        draw.text((40, y), line, fill=0, font=font)
        y += 40
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG", optimize=True)


@pytest.fixture(scope="session")
def golden_images() -> dict[str, Path]:
    """Render every :data:`GOLDEN_CASES` entry to a PNG and return
    a ``{name: path}`` mapping. Skips if Pillow is missing.
    """
    if Image is None:  # pragma: no cover
        pytest.skip("Pillow is not installed; golden fixtures cannot be rendered")
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for case in GOLDEN_CASES:
        target = FIXTURE_DIR / f"{case.name}.png"
        if not target.exists():
            _render_case(case, target)
        out[case.name] = target
    return out


def _tokenise(text: str) -> set[str]:
    """Lowercase + alphanumeric tokenisation. Used by both the
    scorer and the case definitions so the regression check is
    tolerant of casing and punctuation noise."""
    import re

    return {tok for tok in re.findall(r"[a-z0-9]+", text.lower()) if tok}
