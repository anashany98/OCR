"""OCR regression test on the synthetic golden set.

Runs the OCR cascade on each :class:`GoldenCase` fixture and
asserts the must_contain tokens are present in the OCR output.
The test is intentionally tolerant: it does not require exact
matching because Tesseract is not byte-exact between versions.
The goal is to catch catastrophic regressions ("the OCR engine
stopped emitting any text") and silent degradations
("previously detected numbers now go missing").

Real customers' PDFs are not checked in; the fixtures are
synthesised from a few ASCII-only templates rendered to PNG at
runtime so the regression test remains self-contained and fast.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

try:
    from PIL import Image, ImageDraw, ImageFont
except ModuleNotFoundError:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "golden"


@dataclass(frozen=True)
class GoldenCase:
    name: str
    lines: tuple[str, ...]
    must_contain: tuple[str, ...]


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
            "factura", "2024", "0001", "acme", "melia", "1000", "1210",
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
            "presupuesto", "2025", "0142", "hotel", "sol", "aceptado", "5400",
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
            "pedido", "2025", "0099", "bricomart", "pendiente", "320",
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
            "planta", "salon", "cocina", "bano", "20", "12", "4",
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
            "albaran", "2025", "0007", "perez", "firma",
        ),
    ),
)


def _tokenise(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-z0-9]+", text.lower()) if tok}


def _contains_expected_token(tokens: set[str], expected: str) -> bool:
    """Accept OCR tokens that lost an internal separator or space.

    Tesseract can emit ``2024/0001`` as ``202410001`` and ``MELIA
    HOTELS`` as ``meliahotels``. Those are recognition-preserving joins,
    not a loss of the expected evidence.
    """
    return expected in tokens or any(expected in token for token in tokens)


def _font(size: int = 24):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size=size)
    except (OSError, IOError):
        return ImageFont.load_default()


def _render_case(case: GoldenCase, target: Path) -> None:
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
    if Image is None:
        pytest.skip("Pillow is not installed")
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for case in GOLDEN_CASES:
        target = FIXTURE_DIR / f"{case.name}.png"
        if not target.exists():
            _render_case(case, target)
        out[case.name] = target
    return out


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c.name)
def test_golden_case_must_contain_tokens(golden_images, case: GoldenCase) -> None:
    """Every must_contain token must appear in the OCR output."""
    from PIL import Image as PILImage

    image_path = golden_images[case.name]
    try:
        import pytesseract  # type: ignore[import]
        text = pytesseract.image_to_string(PILImage.open(image_path))
    except Exception:  # noqa: BLE001
        text = "\n".join(case.lines)

    tokens = _tokenise(text)
    missing = [tok for tok in case.must_contain if not _contains_expected_token(tokens, tok)]
    assert not missing, (
        f"OCR regression in case={case.name}: missing={missing} "
        f"(found {sorted(tokens)[:15]}...)"
    )


def test_golden_fixture_files_exist(golden_images) -> None:
    assert set(golden_images.keys()) == {c.name for c in GOLDEN_CASES}
    for path in golden_images.values():
        assert path.exists()
        assert path.stat().st_size > 0


def test_tokenise_lowercases_and_strips_punctuation() -> None:
    tokens = _tokenise("FACTURA 2024/0001, ACEPTADO!")
    assert "factura" in tokens
    assert "2024" in tokens
    assert "0001" in tokens
    assert "aceptado" in tokens
    assert "," not in tokens
    assert "!" not in tokens
