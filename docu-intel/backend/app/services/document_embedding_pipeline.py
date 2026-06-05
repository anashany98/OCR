from __future__ import annotations

import logging
import sys as _sys

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import DocumentChunk
from app.services.chunking import build_chunks
from app.services.embeddings import EmbeddingProviderError, embed_many, should_create_embeddings
from app.services.metrics import track_embedding_fallback

logger = logging.getLogger("app.services.document_embedding_pipeline")


def _facade():
    return _sys.modules["app.services.document_service"]


def embed_many_with_metadata(texts: list[str]) -> list[tuple[list[float], str, bool]]:
    """Embed a batch of texts, returning one ``(embedding, provider, fallback)``
    tuple per text.

    On a non-recoverable embedding failure (provider unreachable, model
    can't load, fallback disabled) we return ``(None, "failed", True)``
    for every text instead of raising. Downstream code stores the
    chunks with ``embedding=None`` and ``needs_reembedding=True`` so the
    document survives and an admin can re-trigger embedding later. This
    is the deliberate behaviour the user asked for ("pues que el
    documento se quede sin embedding") — never silently substitute
    hash embeddings when the real one fails.
    """
    if not texts:
        return []
    try:
        embeddings = _facade().embed_many(texts)
    except EmbeddingProviderError as exc:
        logger.warning(
            "Embedding provider failed for %d chunk(s); storing without embedding: %s",
            len(texts),
            exc,
        )
        track_embedding_fallback()
        return [(None, "failed", True) for _ in texts]
    except Exception as exc:  # noqa: BLE001 — surface anything, but never crash the document
        logger.warning(
            "Unexpected embedding error for %d chunk(s); storing without embedding: %s",
            len(texts),
            exc,
        )
        track_embedding_fallback()
        return [(None, "failed", True) for _ in texts]

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


def reembed_document(db: Session, document_id: int) -> dict:
    """Re-run the embedding step for an existing document.

    Re-uses the page texts already stored in ``DocumentPage.text`` so we
    don't re-OCR. Chunks that already have an embedding are overwritten;
    chunks that previously had ``embedding=None`` (e.g. because the
    provider was down during initial processing) get one now.

    Returns a small dict with counts and the provider label so the admin
    UI can show "Re-embedded 42 chunks with ibm-granite/granite-embedding-311m".

    The function never raises on embedding failure — the new
    ``needs_reembedding=True`` flag is preserved so the admin can try
    again. This matches the new "no silent hash fallback" policy.
    """
    from app.models import Document, DocumentChunk, DocumentPage

    document = db.get(Document, document_id)
    if document is None:
        raise ValueError(f"Document {document_id} not found")

    # Load page texts in order. We need (page_number, text) for the
    # chunker to rebuild chunks identically to the original processing.
    pages = list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_number.asc())
        )
    )
    page_texts = [(p.page_number, p.text) for p in pages]

    # Build the new chunks (same as initial processing).
    new_chunks = prepare_document_chunks(document_id, page_texts)

    # Load existing chunks keyed by (page_number, chunk_text) so we can
    # preserve their ids and carry over non-embedding fields.
    existing = list(
        db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id))
    )
    existing_by_key = {(c.page_number, c.chunk_text): c for c in existing}

    updated = 0
    for new_chunk in new_chunks:
        key = (new_chunk.page_number, new_chunk.chunk_text)
        old = existing_by_key.pop(key, None)
        if old is not None:
            old.embedding = new_chunk.embedding
            old.embedding_provider_used = new_chunk.embedding_provider_used
            old.embedding_fallback = new_chunk.embedding_fallback
            old.needs_reembedding = new_chunk.needs_reembedding
            updated += 1
        else:
            db.add(new_chunk)
            updated += 1

    # Delete chunks that no longer exist (e.g. page text changed since
    # the original processing).
    for stale in existing_by_key.values():
        db.delete(stale)

    db.commit()

    provider = settings.embedding_provider
    return {
        "document_id": document_id,
        "chunks_updated": updated,
        "chunks_with_embedding": sum(
            1 for c in new_chunks if c.embedding is not None
        ),
        "chunks_needing_reembedding": sum(
            1 for c in new_chunks if c.needs_reembedding
        ),
        "provider": provider,
    }
