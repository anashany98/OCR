from __future__ import annotations


def build_chunks(text: str, max_words: int = 220, overlap_words: int = 40) -> list[tuple[str, int]]:
    words = text.split()
    if not words:
        return []

    chunks: list[tuple[str, int]] = []
    step = max(1, max_words - overlap_words)
    for start in range(0, len(words), step):
        selected = words[start : start + max_words]
        if selected:
            chunks.append((" ".join(selected), len(selected)))
        if start + max_words >= len(words):
            break
    return chunks

