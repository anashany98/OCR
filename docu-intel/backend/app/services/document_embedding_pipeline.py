from __future__ import annotations

import sys as _sys

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import DocumentChunk
from app.services.chunking import build_chunks
from app.services.embeddings import embed_many, should_create_embeddings
from app.services.metrics import track_embedding_fallback


def _facade():
    return _sys.modules["app.services.document_service"]


def embed_many_with_metadata(texts: list[str]) -> list[tuple[list[float], str, bool]]:
    embeddings = _facade().embed_many(texts)
    provider = settings.embedding_provider.lower().strip() or "local_hash"
    fallback = provider in {"local", "local_hash"}
    return [(embedding, provider, fallback) for embedding in embeddings]


def prepare_document_chunks(document_id: int, page_texts: list[tuple[int, str | None]]) -> list[DocumentChunk]:
    from app.services.document_processing_core import sanitize_text_for_database

    chunk_payloads: list[tuple[int, str, int]] = []
    for page_number, page_text in page_texts:
        clean_text = sanitize_text_for_database(page_text)
        for chunk_text, token_count in build_chunks(clean_text):
            chunk_payloads.append((page_number, chunk_text, token_count))

    embedding_payloads = (
        _facade().embed_many_with_metadata([chunk_text for _, chunk_text, _ in chunk_payloads])
        if chunk_payloads and _facade().should_create_embeddings()
        else [(None, None, False)] * len(chunk_payloads)
    )
    if len(embedding_payloads) != len(chunk_payloads):
        raise ValueError("Embedding count does not match chunk count")

    for _, _, fallback in embedding_payloads:
        if fallback:
            track_embedding_fallback()

    return [
        DocumentChunk(
            document_id=document_id,
            page_number=page_number,
            chunk_text=chunk_text,
            embedding=embedding,
            embedding_provider_used=provider,
            embedding_fallback=fallback,
            needs_reembedding=fallback,
            token_count=token_count,
        )
        for (page_number, chunk_text, token_count), (embedding, provider, fallback) in zip(chunk_payloads, embedding_payloads, strict=True)
    ]


def _replace_document_chunks(db: Session, document_id: int, page_texts: list[tuple[int, str | None]]) -> None:
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    for chunk in prepare_document_chunks(document_id, page_texts):
        db.add(chunk)
    db.flush()
