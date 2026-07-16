"""Safe conversion of OvisOCR2 Markdown into Docu-Intel OCR blocks.

OvisOCR2 returns one Markdown document rather than a word-level OCR layout.
This module deliberately preserves that document verbatim enough for search,
while extracting only evidence-backed table, formula and visual-region blocks.
It never manufactures boxes for content where the model supplied none.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from app.ocr.base import OCRBlock

_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table\s*>", re.IGNORECASE | re.DOTALL)
_VISUAL_REGION_RE = re.compile(
    r"<img\s+[^>]*?src\s*=\s*['\"]images/bbox_"
    r"(-?\d+(?:\.\d+)?)_(-?\d+(?:\.\d+)?)_"
    r"(-?\d+(?:\.\d+)?)_(-?\d+(?:\.\d+)?)\.(?:jpg|jpeg|png)['\"][^>]*>",
    re.IGNORECASE,
)
_FORMULA_RE = re.compile(
    r"(?:\$\$(?P<display>.+?)\$\$|\\\[(?P<bracket>.+?)\\\]|\\\((?P<paren>.+?)\\\)|(?<!\\)\$(?P<inline>[^$\n]{2,})\$)",
    re.DOTALL,
)
_DANGEROUS_TAG_RE = re.compile(
    r"<(?:script|style|iframe|object|embed)[^>]*>.*?</(?:script|style|iframe|object|embed)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_EVENT_HANDLER_RE = re.compile(r"\s+on[a-z]+\s*=\s*(?:'[^']*'|\"[^\"]*\"|[^\s>]+)", re.IGNORECASE)
_EXTERNAL_URL_RE = re.compile(
    r"\s+(?:src|href)\s*=\s*(?:'|\")?(?:https?:|javascript:|data:)[^\s>]*", re.IGNORECASE
)
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_UNSUPPORTED_TAG_RE = re.compile(
    r"</?(?!(?:table|thead|tbody|tr|th|td|br|img)\b)[a-z][^>]*>", re.IGNORECASE
)
_TABLE_TAG_WITH_ATTRIBUTES_RE = re.compile(
    r"<(table|thead|tbody|tr|th|td|br)\b[^>]*>", re.IGNORECASE
)


@dataclass(frozen=True)
class OvisOCR2ParsedOutput:
    markdown: str
    blocks: list[OCRBlock]
    warnings: list[str]


def clean_truncated_repeats(
    text: str,
    *,
    min_text_len: int = 8000,
    max_period: int = 200,
    min_repeat_chars: int = 100,
    min_repeat_times: int = 5,
) -> tuple[str, bool]:
    """Trim the repeating tail pattern documented by the model authors."""
    if len(text) < min_text_len:
        return text, False
    length = len(text)
    for unit_len in range(1, min(max_period, length - 1) + 1):
        if text[-1] != text[-1 - unit_len]:
            continue
        match_len = 1
        index = length - 2
        while index >= unit_len and text[index] == text[index - unit_len]:
            match_len += 1
            index -= 1
        total_len = match_len + unit_len
        if total_len // unit_len >= min_repeat_times and total_len >= min_repeat_chars:
            tail_len = total_len % unit_len
            return text[: length - total_len + unit_len] + text[length - tail_len :], True
    return text, False


def sanitize_ovisocr2_markdown(markdown: str) -> str:
    """Remove executable/remote HTML while retaining document tables.

    Markdown is stored and later rendered by several surfaces.  Keeping only
    table markup and local model-generated bbox tags avoids introducing a
    renderer-specific XSS or a server-side request to an arbitrary URL.
    """
    clean = _DANGEROUS_TAG_RE.sub("", markdown or "")
    clean = _EVENT_HANDLER_RE.sub("", clean)
    clean = _EXTERNAL_URL_RE.sub("", clean)
    # Only table markup and Ovis' documented bbox image tags have a place in
    # persisted Markdown.  Remove every other HTML tag rather than attempting
    # to keep an ever-growing allow-list of browser features/URLs.
    clean = _IMG_TAG_RE.sub(
        lambda match: match.group(0) if _VISUAL_REGION_RE.fullmatch(match.group(0)) else "",
        clean,
    )
    clean = _UNSUPPORTED_TAG_RE.sub("", clean)
    clean = _TABLE_TAG_WITH_ATTRIBUTES_RE.sub(lambda match: f"<{match.group(1).lower()}>", clean)
    return clean.strip()


def _normalise_bbox(
    raw: tuple[str, str, str, str], width: float, height: float
) -> tuple[float, float, float, float] | None:
    try:
        left, top, right, bottom = (float(value) for value in raw)
    except ValueError:
        return None
    left, top, right, bottom = (
        max(0.0, min(1000.0, value)) for value in (left, top, right, bottom)
    )
    if right <= left or bottom <= top:
        return None
    return (
        left * width / 1000.0,
        top * height / 1000.0,
        right * width / 1000.0,
        bottom * height / 1000.0,
    )


def parse_ovisocr2_output(
    markdown: str,
    *,
    image_width: float,
    image_height: float,
    finish_reason: str | None = None,
    keep_visual_regions: bool = True,
    max_blocks: int = 512,
    max_characters: int = 2_000_000,
) -> OvisOCR2ParsedOutput:
    """Parse an OvisOCR2 response without trusting its structure blindly."""
    warnings: list[str] = []
    clean = sanitize_ovisocr2_markdown((markdown or "")[:max_characters])
    if len(markdown or "") > max_characters:
        warnings.append("response_character_limit")
    clean, repeated = clean_truncated_repeats(clean)
    if repeated:
        warnings.append("repetitive_tail_removed")
    if (finish_reason or "").lower() == "length":
        warnings.append("truncated_output")
    if not clean:
        warnings.append("empty_output")
        return OvisOCR2ParsedOutput(markdown="", blocks=[], warnings=warnings)

    blocks: list[OCRBlock] = [OCRBlock(text=clean, confidence=None, bbox=None, block_type="text")]
    for table in _TABLE_RE.findall(clean):
        if len(blocks) >= max_blocks:
            warnings.append("block_limit")
            break
        # Escape only malformed bare angle content outside of the table; table
        # elements themselves have already had executable attributes stripped.
        blocks.append(OCRBlock(text=table.strip(), confidence=None, bbox=None, block_type="table"))
    for match in _FORMULA_RE.finditer(clean):
        if len(blocks) >= max_blocks:
            warnings.append("block_limit")
            break
        formula = next(
            (value for value in match.groupdict().values() if value is not None), ""
        ).strip()
        if formula:
            blocks.append(OCRBlock(text=formula, confidence=None, bbox=None, block_type="formula"))
    if keep_visual_regions:
        for match in _VISUAL_REGION_RE.finditer(clean):
            if len(blocks) >= max_blocks:
                warnings.append("block_limit")
                break
            bbox = _normalise_bbox(match.groups(), image_width, image_height)
            if bbox is None:
                warnings.append("invalid_visual_region")
                continue
            blocks.append(
                OCRBlock(
                    text=html.unescape(match.group(0)),
                    confidence=None,
                    bbox=bbox,
                    block_type="figure",
                )
            )
    return OvisOCR2ParsedOutput(markdown=clean, blocks=blocks, warnings=warnings)


__all__ = [
    "OvisOCR2ParsedOutput",
    "clean_truncated_repeats",
    "parse_ovisocr2_output",
    "sanitize_ovisocr2_markdown",
]
