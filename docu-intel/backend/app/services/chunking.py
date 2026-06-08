from __future__ import annotations

import re


_PARAGRAPH_RE = re.compile(r"\n\s*\n+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def build_chunks(
    text: str,
    max_words: int = 220,
    overlap_words: int = 40,
) -> list[tuple[str, int]]:
    max_words = max(1, int(max_words))
    overlap_words = max(0, min(int(overlap_words), max_words - 1))
    paragraphs = _paragraph_sentences(text)
    if not paragraphs:
        return []

    chunks: list[tuple[str, int]] = []
    for paragraph in paragraphs:
        current_units: list[str] = []
        current_words = 0
        for sentence in paragraph:
            for unit in _split_oversized_sentence(sentence, max_words, overlap_words):
                unit_words = _word_count(unit)
                if current_units and current_words + unit_words > max_words:
                    _append_chunk(chunks, current_units)
                    current_units, current_words = _overlap_units(current_units, overlap_words)
                if current_units and current_words + unit_words > max_words:
                    current_units = []
                    current_words = 0
                current_units.append(unit)
                current_words += unit_words
        if current_units:
            _append_chunk(chunks, current_units)
    return chunks


def embedding_text_with_metadata(
    chunk_text: str,
    *,
    document_type: str | None = None,
    filename: str | None = None,
    page_number: int | None = None,
) -> str:
    header = chunk_metadata_header(
        document_type=document_type,
        filename=filename,
        page_number=page_number,
    )
    if not header:
        return chunk_text
    return f"{header} {chunk_text}"


def chunk_metadata_header(
    *,
    document_type: str | None = None,
    filename: str | None = None,
    page_number: int | None = None,
) -> str:
    fields: list[str] = []
    if document_type:
        fields.append(f"tipo={_metadata_value(document_type)}")
    if filename:
        fields.append(f"fichero={_metadata_value(filename)}")
    if page_number is not None:
        fields.append(f"pág={int(page_number)}")
    if not fields:
        return ""
    return "[" + " | ".join(fields) + "]"


def _paragraph_sentences(text: str) -> list[list[str]]:
    paragraphs: list[list[str]] = []
    for paragraph in _PARAGRAPH_RE.split(text or ""):
        clean = " ".join(paragraph.split())
        if not clean:
            continue
        sentences = [
            sentence.strip()
            for sentence in _SENTENCE_RE.split(clean)
            if sentence.strip()
        ]
        paragraphs.append(sentences or [clean])
    return paragraphs


def _split_oversized_sentence(sentence: str, max_words: int, overlap_words: int) -> list[str]:
    words = sentence.split()
    if len(words) <= max_words:
        return [sentence]
    step = max(1, max_words - overlap_words)
    chunks: list[str] = []
    for start in range(0, len(words), step):
        selected = words[start : start + max_words]
        if selected:
            chunks.append(" ".join(selected))
        if start + max_words >= len(words):
            break
    return chunks


def _overlap_units(units: list[str], overlap_words: int) -> tuple[list[str], int]:
    if overlap_words <= 0:
        return [], 0
    selected: list[str] = []
    total = 0
    for unit in reversed(units):
        count = _word_count(unit)
        if selected and total + count > overlap_words:
            break
        if not selected and count > overlap_words:
            break
        selected.append(unit)
        total += count
    selected.reverse()
    return selected, total


def _append_chunk(chunks: list[tuple[str, int]], units: list[str]) -> None:
    text = " ".join(unit.strip() for unit in units if unit.strip())
    if text:
        chunks.append((text, _word_count(text)))


def _word_count(text: str) -> int:
    return len(text.split())


def _metadata_value(value: str) -> str:
    return " ".join(str(value).replace("|", " ").split())
