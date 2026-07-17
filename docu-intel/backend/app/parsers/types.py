from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExtractedBlock:
    block_type: str
    text: str
    page_number: int
    bbox: tuple[float, float, float, float] | None = None
    confidence: float | None = None
    source_engine: str | None = None


@dataclass(frozen=True)
class CadMetadata:
    """Stable provenance for a native CAD extraction."""

    source_format: str
    unit: str | None = None
    unit_code: int | None = None
    layers: tuple[str, ...] = ()
    extents: tuple[float, float, float, float] | None = None
    layout: str = "modelspace"
    converter: str | None = None
    dxf_version: str | None = None
    converter_version: str | None = None


@dataclass(frozen=True)
class CadDimensionEntity:
    entity_handle: str | None
    layer: str
    value: float | None
    displayed_text: str | None
    native_unit: str | None
    unit_source: str
    normalized_value_m: float | None
    definition_points: tuple[tuple[float, float], ...] = ()
    text_point: tuple[float, float] | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class CadGeometryEntity:
    entity_handle: str | None
    entity_type: str
    layer: str
    geometry: dict
    closed: bool = False


@dataclass(frozen=True)
class CadInsertEntity:
    entity_handle: str | None
    block_name: str
    layer: str
    insertion_point: tuple[float, float]
    attributes: dict[str, str] = field(default_factory=dict)
    rotation: float | None = None
    scale: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class CadTextEntity:
    entity_handle: str | None
    text: str
    layer: str
    insertion_point: tuple[float, float] | None = None


@dataclass(frozen=True)
class CadExtraction:
    """Native CAD entities retained alongside the searchable page text."""

    metadata: CadMetadata
    dimensions: tuple[CadDimensionEntity, ...] = ()
    geometry: tuple[CadGeometryEntity, ...] = ()
    inserts: tuple[CadInsertEntity, ...] = ()
    texts: tuple[CadTextEntity, ...] = ()


@dataclass
class ExtractedPage:
    page_number: int
    text: str
    width: float | None = None
    height: float | None = None
    image_path: str | None = None
    ocr_confidence: float | None = None
    # ``native_text`` and ``decorative`` pages remain searchable, but do not
    # participate in OCR quality metrics or the OCR-review queue.
    ocr_content_kind: str | None = None
    # Which engine produced this page's text. One of: pymupdf, paddleocr, empty.
    # The ``empty`` label marks pages routed to OCR that still produced no
    # usable text — useful for spotting low-quality scans.
    ocr_engine: str | None = None
    # Optional immutable model/engine revision.  Kept separate from the stable
    # name so the re-OCR sweep can target a stale remote model safely.
    ocr_engine_version: str | None = None
    # Non-fatal parser/service warnings (e.g. an OvisOCR2 token truncation).
    # The persistence layer turns these into conservative decision reasons.
    ocr_warnings: list[str] = field(default_factory=list)
    blocks: list[ExtractedBlock] = field(default_factory=list)


@dataclass
class ExtractedDocument:
    pages: list[ExtractedPage]
    # Optional typed CAD payload. Existing parser consumers only need pages
    # and therefore remain backwards compatible.
    cad: CadExtraction | None = None

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text)
