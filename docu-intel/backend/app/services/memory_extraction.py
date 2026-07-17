"""PM4.1/PM4.2 — Structured memory parsing and specification extraction.

Construction memories (memoria descriptiva, memoria constructiva) have
a hierarchical structure: chapters → subchapters → paragraphs → lists.
This module parses that structure and extracts technical specifications
with full provenance.

PM4.1: Hierarchical parsing with chunk metadata.
PM4.2: Technical specification extraction with evidence.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("app.services.memory_extraction")


# ---------------------------------------------------------------------------
# PM4.1 — Hierarchical document structure
# ---------------------------------------------------------------------------


@dataclass
class DocumentSection:
    """A section in a hierarchical document structure."""

    heading: str
    level: int  # 1=chapter, 2=subchapter, 3=sub-subchapter
    page_number: int | None = None
    children: list[DocumentSection] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    tables: list[list[list[str]]] = field(
        default_factory=list
    )  # list of rows, each row is list of cells


@dataclass
class StructuredChunk:
    """A chunk with hierarchical context for embedding."""

    text: str
    token_count: int
    chunk_type: str = "text"
    # PM4.1: Hierarchical path
    chapter_path: str = ""  # e.g. "Memoria constructiva → 4 Cerramientos → 4.2 Tabiquería"
    chapter_number: str = ""  # e.g. "4.2"
    page_number: int | None = None
    document_type: str | None = None
    filename: str | None = None

    def embedding_text(self) -> str:
        """Build embedding text with metadata prepend (PM4.1 format)."""
        parts = []
        if self.document_type:
            parts.append(f"documento={self.document_type}")
        if self.filename:
            parts.append(f"fichero={self.filename}")
        if self.chapter_path:
            parts.append(f"capítulo={self.chapter_path}")
        if self.page_number is not None:
            parts.append(f"pág={self.page_number}")

        header = "[" + " | ".join(parts) + "]" if parts else ""
        return f"{header} {self.text}" if header else self.text


# ---------------------------------------------------------------------------
# PM4.1 — Section parsing patterns
# ---------------------------------------------------------------------------

# Chapter headings: "4 Cerramientos", "4.2 Tabiquería interior"
_CHAPTER_RE = re.compile(
    r"^(\d+(?:\.\d+)*)\s+(.+?)(?:\s*$)",
    re.MULTILINE,
)
# Numbered heading: "1.1.1 Sub-subchapter"
_NUMBERED_HEADING_RE = re.compile(
    r"^(\d+(?:\.\d+){0,3})\s+(.+?)(?:\s*$)",
    re.MULTILINE,
)
# All-caps heading: "CERRAMIENTOS"
_CAPS_HEADING_RE = re.compile(
    r"^([A-ZÁÉÍÓÚÑ0-9 .,/\-]{4,80})\s*$",
    re.MULTILINE,
)
# Table row (markdown or space-aligned)
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_SPACE_TABLE_RE = re.compile(r"\S(?:.*?\S)?(?:\s{2,}|\t+)\S")
# Paragraph separator
_PARAGRAPH_SEP = re.compile(r"\n\s*\n+")


def parse_memory_structure(text: str, document_type: str | None = None) -> list[DocumentSection]:
    """Parse a construction memory into hierarchical sections.

    Detects chapters, subchapters, paragraphs, and tables.
    Returns a list of top-level sections with nested children.
    """
    lines = text.split("\n")
    sections: list[DocumentSection] = []
    current_section: DocumentSection | None = None
    current_paragraphs: list[str] = []
    current_tables: list[list[list[str]]] = []

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        # Check for numbered heading
        numbered_match = _NUMBERED_HEADING_RE.match(line)
        if numbered_match:
            # Save current section content
            if current_section:
                current_section.paragraphs = current_paragraphs
                current_section.tables = current_tables
                current_paragraphs = []
                current_tables = []

            number = numbered_match.group(1)
            heading = numbered_match.group(2).strip()
            level = number.count(".") + 1

            new_section = DocumentSection(
                heading=f"{number} {heading}",
                level=level,
                paragraphs=[],
                tables=[],
            )

            # Determine parent based on level
            if level == 1:
                sections.append(new_section)
                current_section = new_section
            elif level == 2 and sections:
                sections[-1].children.append(new_section)
                current_section = new_section
            elif level >= 3 and sections and sections[-1].children:
                sections[-1].children[-1].children.append(new_section)
                current_section = new_section
            else:
                sections.append(new_section)
                current_section = new_section

            i += 1
            continue

        # Check for all-caps heading (fallback)
        caps_match = _CAPS_HEADING_RE.match(line)
        if caps_match and len(line.strip()) > 3 and not line.strip().startswith("|"):
            heading_text = caps_match.group(1).strip()
            # Skip if it looks like a table header or data
            if not any(c in heading_text for c in ["|", "─", "═"]):
                if current_section:
                    current_section.paragraphs = current_paragraphs
                    current_section.tables = current_tables
                    current_paragraphs = []
                    current_tables = []

                new_section = DocumentSection(
                    heading=heading_text,
                    level=1,
                    paragraphs=[],
                    tables=[],
                )
                sections.append(new_section)
                current_section = new_section
                i += 1
                continue

        # Check for table
        if _TABLE_ROW_RE.match(line):
            table_rows = []
            while i < len(lines) and _TABLE_ROW_RE.match(lines[i].rstrip()):
                row_text = lines[i].rstrip()
                # Parse cells
                cells = [c.strip() for c in row_text.strip("|").split("|")]
                table_rows.append(cells)
                i += 1
            if table_rows:
                current_tables.append(table_rows)
            continue

        # Check for space-aligned table
        if _SPACE_TABLE_RE.search(line) and len(line.strip()) > 10:
            # Peek ahead to see if next lines also look like table rows
            table_lines = [line]
            j = i + 1
            while j < len(lines) and j < i + 20:
                next_line = lines[j].rstrip()
                if not next_line.strip():
                    break
                if _SPACE_TABLE_RE.search(next_line):
                    table_lines.append(next_line)
                    j += 1
                else:
                    break

            if len(table_lines) >= 2:
                # Parse as table
                table_rows = []
                for tl in table_lines:
                    cells = re.split(r"\s{2,}|\t+", tl.strip())
                    table_rows.append(cells)
                current_tables.append(table_rows)
                i = j
                continue

        # Regular paragraph text
        if line.strip():
            current_paragraphs.append(line.strip())

        i += 1

    # Save last section
    if current_section:
        current_section.paragraphs = current_paragraphs
        current_section.tables = current_tables

    return sections


def sections_to_chunks(
    sections: list[DocumentSection],
    document_type: str | None = None,
    filename: str | None = None,
    max_words: int = 220,
) -> list[StructuredChunk]:
    """Convert hierarchical sections to structured chunks.

    Each chunk includes the full chapter path for embedding context.
    """
    chunks: list[StructuredChunk] = []

    def _process_section(section: DocumentSection, parent_path: str = ""):
        current_path = f"{parent_path} → {section.heading}" if parent_path else section.heading
        chapter_num = section.heading.split(" ")[0] if section.heading else ""

        # Emit paragraphs as chunks
        if section.paragraphs:
            paragraph_text = " ".join(section.paragraphs)
            word_count = len(paragraph_text.split())

            if word_count <= max_words:
                chunks.append(
                    StructuredChunk(
                        text=paragraph_text,
                        token_count=word_count,
                        chunk_type="text",
                        chapter_path=current_path,
                        chapter_number=chapter_num,
                        document_type=document_type,
                        filename=filename,
                    )
                )
            else:
                # Split long paragraphs
                sentences = re.split(r"(?<=[.!?])\s+", paragraph_text)
                current_chunk = []
                current_words = 0
                for sent in sentences:
                    sent_words = len(sent.split())
                    if current_words + sent_words > max_words and current_chunk:
                        chunks.append(
                            StructuredChunk(
                                text=" ".join(current_chunk),
                                token_count=current_words,
                                chunk_type="text",
                                chapter_path=current_path,
                                chapter_number=chapter_num,
                                document_type=document_type,
                                filename=filename,
                            )
                        )
                        current_chunk = []
                        current_words = 0
                    current_chunk.append(sent)
                    current_words += sent_words
                if current_chunk:
                    chunks.append(
                        StructuredChunk(
                            text=" ".join(current_chunk),
                            token_count=current_words,
                            chunk_type="text",
                            chapter_path=current_path,
                            chapter_number=chapter_num,
                            document_type=document_type,
                            filename=filename,
                        )
                    )

        # Emit tables as chunks
        for table in section.tables:
            table_text = _format_table(table)
            if table_text:
                chunks.append(
                    StructuredChunk(
                        text=table_text,
                        token_count=len(table_text.split()),
                        chunk_type="table",
                        chapter_path=current_path,
                        chapter_number=chapter_num,
                        document_type=document_type,
                        filename=filename,
                    )
                )

        # Process children
        for child in section.children:
            _process_section(child, current_path)

    for section in sections:
        _process_section(section)

    return chunks


def _format_table(table: list[list[str]]) -> str:
    """Format a table as readable text for embedding."""
    if not table:
        return ""
    rows = []
    for row in table:
        rows.append(" | ".join(str(cell) for cell in row))
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# PM4.2 — Technical specification extraction
# ---------------------------------------------------------------------------


@dataclass
class TechnicalSpec:
    """A technical specification extracted from a construction memory."""

    # Identification
    system_element: str  # e.g. "Tabiquería interior"
    location: str | None = None  # e.g. "Planta Baja", "Dormitorio 1"

    # Material properties
    material: str | None = None  # e.g. "Pladur"
    product_reference: str | None = None  # e.g. "Fassa Bartolo PL40"
    thickness_cm: float | None = None
    width_cm: float | None = None
    height_cm: float | None = None

    # Performance
    fire_rating: str | None = None  # e.g. "REI 60"
    acoustic_rating: str | None = None  # e.g. "Rw = 45 dB"
    thermal_insulation: str | None = None  # e.g. "U = 0.35 W/m²K"

    # Execution
    installation_method: str | None = None
    tolerances: str | None = None
    quality_control: str | None = None
    maintenance: str | None = None

    # Standards
    cited_standards: list[str] = field(default_factory=list)

    # Evidence
    document_id: int | None = None
    page_number: int | None = None
    source_text: str = ""
    confidence: float = 0.0
    chapter_path: str = ""


# PM4.2 patterns for specification extraction
_MATERIAL_RE = re.compile(
    r"(?:material|tipo)\s*[:=]\s*([A-Za-zÁÉÍÓÚÑáéíóúñ][A-Za-zÁÉÍÓÚÑáéíóúñ0-9 /,\-]+)",
    re.IGNORECASE,
)
_THICKNESS_RE = re.compile(
    r"(?:espesor|grosor|groso)\s*[:=]?\s*(?:de\s*)?(\d+(?:[.,]\d+)?)\s*(cm|mm|m)\b|(\d+(?:[.,]\d+)?)\s*(cm|mm|m)\s*(?:de\s+)?(?:espesor|grosor|groso)",
    re.IGNORECASE,
)
_DIMENSION_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(cm|mm|m)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*(cm|mm|m)",
    re.IGNORECASE,
)
_FIRE_RE = re.compile(
    r"(?:[Rr]ea(?:ci[oó]n|ctividad)\s+al\s+fuego|[Cc]lase\s+de\s+fuego|[Ff]ire\s+rating)\s*[:=]?\s*([A-Z]{2,4}\s*\d{1,3})|(?<!\w)(REI\s*\d{1,3})(?!\w)",
    re.IGNORECASE,
)
_ACOUSTIC_RE = re.compile(
    r"(?:aislamiento\s+ac[uú]stico|[Ii]ndice\s+de\s+reducci[oó]n\s+ac[uú]stica)\s*[:=]?\s*(Rw\s*=\s*\d+\s*dB|L'n,w\s*=\s*\d+\s*dB|\d+\s*dB)|(?<!\w)(Rw\s*=\s*\d+\s*dB)(?!\w)|(?<!\w)(L'n,w\s*=\s*\d+\s*dB)(?!\w)",
    re.IGNORECASE,
)
_THERMAL_RE = re.compile(
    r"(?:aislamiento\s+t[eé]rmico|[Cc]oeficiente\s+de\s+transmitancia)\s*[:=]?\s*(U\s*=\s*\d+(?:[.,]\d+)?\s*W/m[²2]K)|(?<!\w)(U\s*=\s*\d+(?:[.,]\d+)?\s*W/m[²2]K)(?!\w)",
    re.IGNORECASE,
)
_STANDARD_RE = re.compile(
    r"(?:[Ee]norma|[Ss]tandard|[Uu]NE|[Ee]uroc[oó]digo)\s*[:=]?\s*([A-Z]{2,5}[\s\-]?\d+(?:[.:]\d+)*(?:[-:]\d+)?)",
    re.IGNORECASE,
)
# Also match standalone standards like "UNE-EN 806" or "EN 14190:2014"
_STANDALONE_STANDARD_RE = re.compile(
    r"(?<!\w)([A-Z]{2,5}[\s\-]?\d+(?:[.:]\d+)*(?:[-:]\d+)?)(?!\w)",
    re.IGNORECASE,
)
_INSTALLATION_RE = re.compile(
    r"(?:instalaci[oó]n|m[eé]todo\s+de\s+ejecuci[oó]n)\s*[:=]\s*(.+?)(?:\.|$)",
    re.IGNORECASE,
)
_TOLERANCES_RE = re.compile(
    r"(?:tolerancias?|precisiones?)\s*[:=]\s*(.+?)(?:\.|$)",
    re.IGNORECASE,
)
_MAINTENANCE_RE = re.compile(
    r"(?:mantenimiento)\s*[:=]\s*(.+?)(?:\.|$)",
    re.IGNORECASE,
)
_LOCATION_RE = re.compile(
    r"(?:ubicaci[oó]n|localizaci[oó]n|emplazamiento|zona|planta|estancia)\s*[:=]\s*([A-Za-zÁÉÍÓÚÑáéíóúñ][A-Za-zÁÉÍÓÚÑáéíóúñ0-9 ]+)",
    re.IGNORECASE,
)


def extract_specifications(
    text: str,
    document_id: int | None = None,
    page_number: int | None = None,
    chapter_path: str = "",
) -> list[TechnicalSpec]:
    """Extract technical specifications from memory text.

    First parses the document structure, then extracts specs per
    subsection using the section heading as the system_element.
    Falls back to paragraph-based extraction for unstructured text.
    """
    # Parse document structure
    sections = parse_memory_structure(text)

    # If we found sections, extract per section
    if sections:
        specs: list[TechnicalSpec] = []

        def _extract_from_section(section: DocumentSection, parent_path: str = ""):
            current_path = f"{parent_path} → {section.heading}" if parent_path else section.heading

            # Combine all paragraphs in this section
            section_text = "\n".join(section.paragraphs)

            # Extract specs from this section's text
            section_specs = _extract_specs_from_text(
                section_text,
                system_element=section.heading,
                document_id=document_id,
                page_number=page_number,
                chapter_path=current_path,
            )
            specs.extend(section_specs)

            # Process children
            for child in section.children:
                _extract_from_section(child, current_path)

        for section in sections:
            _extract_from_section(section)

        return specs

    # Fallback: extract from unstructured text
    return _extract_specs_from_text(
        text,
        system_element="General",
        document_id=document_id,
        page_number=page_number,
        chapter_path=chapter_path,
    )


def _extract_specs_from_text(
    text: str,
    system_element: str,
    document_id: int | None = None,
    page_number: int | None = None,
    chapter_path: str = "",
) -> list[TechnicalSpec]:
    """Extract specs from a single section's text."""
    specs = []
    if not text.strip():
        return specs

    # Extract all properties from the text
    material = _extract_first(_MATERIAL_RE, text)
    thickness = _extract_thickness(_THICKNESS_RE, text)
    fire = _extract_first(_FIRE_RE, text)
    acoustic = _extract_first(_ACOUSTIC_RE, text)
    thermal = _extract_first(_THERMAL_RE, text)
    # Standards: try explicit pattern first, then standalone
    standards = _STANDARD_RE.findall(text)
    if not standards:
        standards = _STANDALONE_STANDARD_RE.findall(text)
    # Filter out fire ratings (REI) which are not standards
    standards = [s for s in standards if not s.upper().startswith("REI")]
    location = _extract_first(_LOCATION_RE, text)
    installation = _extract_first(_INSTALLATION_RE, text)
    tolerances = _extract_first(_TOLERANCES_RE, text)
    maintenance = _extract_first(_MAINTENANCE_RE, text)

    # Also try to extract material from context (e.g. "hormigón armado")
    if not material:
        material_ctx = re.search(
            r"(hormig[oó]n\s+(?:armado|cellular|aligerado)|ladrillo|pladur|yeso|madera|acero|poliestireno|lana\s+de\s+roca)",
            text,
            re.IGNORECASE,
        )
        if material_ctx:
            material = material_ctx.group(1)

    # Create spec if we have at least one meaningful extraction
    has_data = any([material, thickness, fire, acoustic, thermal, standards])
    if not has_data:
        return specs

    spec = TechnicalSpec(
        system_element=system_element,
        location=location,
        material=material,
        thickness_cm=thickness,
        fire_rating=fire,
        acoustic_rating=acoustic,
        thermal_insulation=thermal,
        cited_standards=standards,
        installation_method=installation,
        tolerances=tolerances,
        maintenance=maintenance,
        document_id=document_id,
        page_number=page_number,
        source_text=text[:500],
        confidence=_compute_confidence(material, thickness, fire, acoustic, thermal, standards),
        chapter_path=chapter_path,
    )
    specs.append(spec)

    return specs


def _extract_first(pattern: re.Pattern, text: str) -> str | None:
    """Extract first non-None match group."""
    match = pattern.search(text)
    if match:
        # Return the first non-None group
        for g in match.groups():
            if g is not None:
                return g.strip()
    return None


def _extract_thickness(pattern: re.Pattern, text: str) -> float | None:
    """Extract thickness in cm from pattern match."""
    match = pattern.search(text)
    if not match:
        return None
    # Find the first non-None value/unit pair
    groups = match.groups()
    # Pattern has 4 groups: (value1, unit1, value2, unit2)
    if groups[0] and groups[1]:
        value = float(groups[0].replace(",", "."))
        unit = groups[1].lower()
    elif groups[2] and groups[3]:
        value = float(groups[2].replace(",", "."))
        unit = groups[3].lower()
    else:
        return None
    if unit == "mm":
        return value / 10
    elif unit == "m":
        return value * 100
    return value


def _compute_confidence(
    material: str | None,
    thickness: float | None,
    fire: str | None,
    acoustic: str | None,
    thermal: str | None,
    standards: list[str],
) -> float:
    """Compute confidence score based on extracted fields."""
    score = 0.3  # Base
    if material:
        score += 0.15
    if thickness:
        score += 0.1
    if fire:
        score += 0.1
    if acoustic:
        score += 0.1
    if thermal:
        score += 0.1
    if standards:
        score += 0.1 * min(len(standards), 3)
    return min(0.95, score)


__all__ = [
    "DocumentSection",
    "StructuredChunk",
    "TechnicalSpec",
    "parse_memory_structure",
    "sections_to_chunks",
    "extract_specifications",
]
