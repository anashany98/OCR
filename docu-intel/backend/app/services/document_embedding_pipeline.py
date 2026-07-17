from __future__ import annotations

import logging
import sys

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import DocumentChunk
from app.services.chunking import build_chunks, embedding_text_with_metadata
from app.services.embeddings import EmbeddingProviderError, embed_many, should_create_embeddings
from app.services.metrics import track_embedding_fallback

logger = logging.getLogger("app.services.document_embedding_pipeline")

# This module used to look up its sibling helpers through a
# ``_facade()`` helper that reached into
# ``sys.modules["app.services.document_service"]`` at call
# time. The indirection was needed because the sibling re-export
# hub imported this module, so a top-level import would have
# created a cycle. We now import the helpers directly (lines
# 12) and there is no cycle: ``app.services.embeddings`` and
# ``app.services.chunking`` are leaves that do not import
# anything from this module or from ``document_service``.


def _should_create_embeddings() -> bool:
    facade = sys.modules.get("app.services.document_service")
    if facade is not None:
        return getattr(facade, "should_create_embeddings", should_create_embeddings)()
    return should_create_embeddings()


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
    # Keep the public ``document_service`` facade patchable for callers and
    # tests without reintroducing an import cycle.  When it exposes an
    # explicit replacement, delegate once; the identity guard prevents the
    # normal re-export from recursing back into this function.
    facade = sys.modules.get("app.services.document_service")
    override = getattr(facade, "embed_many_with_metadata", None) if facade else None
    if override is not None and override is not embed_many_with_metadata:
        return override(texts)
    try:
        embeddings = embed_many(texts)
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
    # ``local_hash`` is an explicit configured provider, not an emergency
    # fallback. A successfully generated vector must therefore clear the
    # re-embed queue; only an actual provider error above marks it pending.
    return [(embedding, provider, False) for embedding in embeddings]


def _truncate_to_token_budget(text: str, max_tokens: int) -> str:
    """Truncate ``text`` to roughly ``max_tokens`` model tokens.

    The embedding stack is word-based (see ``chunking._word_count``), and a
    Spanish word averages ~1.3 BPE tokens, so we cap the word count at
    ``max_tokens`` to stay safely under the model's context window (bge-m3
    supports 8K tokens; the default budget of 6000 leaves headroom for the
    metadata and model overhead). Truncating by words also guarantees we
    never split a word in half.
    """
    if max_tokens <= 0 or not text:
        return text or ""
    words = text.split()
    if len(words) <= max_tokens:
        return text
    return " ".join(words[:max_tokens])


def compute_document_embedding(
    page_texts: list[tuple[int, str | None]],
) -> tuple[list[float] | None, str, bool]:
    """Compute a single embedding for the whole document.

    Concatenates the (sanitised) text of every page, truncates it to the
    configured token budget, and embeds it as one passage. The result is
    stored on ``Document.embedding`` and used by the document-level retrieval
    branch to improve thematic recall (documents whose overall topic matches
    even when no isolated chunk does).

    Reuses :func:`embed_many_with_metadata` so the failure contract is
    identical to per-chunk embedding: on any provider failure we return
    ``(None, "failed", True)`` — never a silent hash fallback.
    """
    from app.services.document_processing_core import sanitize_text_for_database

    parts: list[str] = []
    for _page_number, page_text in page_texts:
        clean = sanitize_text_for_database(page_text)
        if clean:
            parts.append(clean)
    if not parts:
        return (None, "empty", False)
    if not _should_create_embeddings():
        return (None, None, False)

    doc_text = _truncate_to_token_budget("\n".join(parts), settings.document_embedding_max_tokens)
    if not doc_text.strip():
        return (None, "empty", False)

    embeddings = embed_many_with_metadata([doc_text])
    if not embeddings:
        return (None, "failed", True)
    embedding, provider, fallback = embeddings[0]
    return (embedding, provider, fallback)


def apply_document_embedding(
    db: Session,
    document_id: int,
    page_texts: list[tuple[int, str | None]],
) -> bool:
    """Populate ``Document.embedding`` for ``document_id``.

    Returns ``True`` when an embedding was produced, ``False`` when it was
    skipped (no text, embeddings disabled, or provider failure — in which
    case ``needs_reembedding`` is set on the document so the re-embed sweep
    retries it later). Safe to call from the ingestion worker: it never
    raises on embedding failure, matching the chunk pipeline's policy.
    """
    from app.models import Document

    document = db.get(Document, document_id)
    if document is None:
        return False

    embedding, provider, fallback = compute_document_embedding(page_texts)
    document.embedding = embedding
    document.embedding_provider_used = provider
    document.embedding_fallback = fallback
    document.needs_reembedding = fallback or (embedding is None and provider == "failed")
    document.embedding_model_version = settings.embedding_model if embedding is not None else None
    if fallback:
        track_embedding_fallback()
    db.flush()
    return embedding is not None


def prepare_document_chunks(
    document_id: int,
    page_texts: list[tuple[int, str | None]],
    *,
    document_type: str | None = None,
    original_filename: str | None = None,
) -> list[DocumentChunk]:
    from app.services.document_processing_core import sanitize_text_for_database

    chunk_payloads: list[tuple[int, str, str, int, str]] = []
    for page_number, page_text in page_texts:
        clean_text = sanitize_text_for_database(page_text)
        # E1 — the chunker now returns Chunk dataclasses. We pull
        # the text/token_count/chunk_type from the dataclass
        # attributes (the dataclass's tuple-unpacking protocol
        # stays 2-tuple for legacy callers).
        for chunk in build_chunks(
            clean_text,
            max_words=settings.embedding_chunk_max_words,
            overlap_words=settings.embedding_chunk_overlap_words,
            respect_tables=settings.embedding_chunk_respect_tables,
            respect_headings=settings.embedding_chunk_respect_headings,
        ):
            chunk_text = chunk.text
            token_count = chunk.token_count
            chunk_type = chunk.chunk_type
            embedding_text = embedding_text_with_metadata(
                chunk_text,
                document_type=document_type,
                filename=original_filename,
                page_number=page_number,
            )
            chunk_payloads.append(
                (page_number, chunk_text, embedding_text, token_count, chunk_type)
            )

    embedding_payloads = (
        embed_many_with_metadata([embedding_text for _, _, embedding_text, _, _ in chunk_payloads])
        if chunk_payloads and _should_create_embeddings()
        else [(None, None, False)] * len(chunk_payloads)
    )
    if len(embedding_payloads) != len(chunk_payloads):
        raise ValueError("Embedding count does not match chunk count")

    for _, _, fallback in embedding_payloads:
        if fallback:
            track_embedding_fallback()

    chunks: list[DocumentChunk] = []
    for (page_number, chunk_text, _, token_count, chunk_type), (
        embedding,
        provider,
        fallback,
    ) in zip(chunk_payloads, embedding_payloads, strict=True):
        chunk = DocumentChunk(
            document_id=document_id,
            page_number=page_number,
            chunk_text=chunk_text,
            embedding=embedding,
            embedding_provider_used=provider,
            embedding_fallback=fallback,
            needs_reembedding=fallback,
            token_count=token_count,
        )
        # ``chunk_type`` may not exist on the ORM column yet (the
        # migration is in 0020 but a deployment that has not
        # migrated would 500 on assignment). We set it via
        # ``setattr`` so the legacy code path still works.
        chunk.chunk_type = chunk_type
        # E4 — record which model version produced this embedding
        # so the periodic re-embed sweep can find chunks that need
        # updating when the operator changes EMBEDDING_MODEL.
        chunk.embedding_model_version = settings.embedding_model
        chunks.append(chunk)
    return chunks


def _replace_document_chunks(
    db: Session,
    document_id: int,
    page_texts: list[tuple[int, str | None]],
    *,
    document_type: str | None = None,
    original_filename: str | None = None,
) -> None:
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    for chunk in prepare_document_chunks(
        document_id,
        page_texts,
        document_type=document_type,
        original_filename=original_filename,
    ):
        db.add(chunk)
    db.flush()
    # Populate the whole-document embedding used by the document-level
    # retrieval branch. Done here so every caller that rebuilds chunks
    # (full parse, embeddings-only reprocess, OCR re-run) refreshes
    # ``Document.embedding`` consistently instead of relying on each
    # caller to remember.
    apply_document_embedding(db, document_id, page_texts)


def persist_chunks_without_embeddings(
    db: Session,
    document_id: int,
    page_texts: list[tuple[int, str | None]],
    *,
    document_type: str | None = None,
    original_filename: str | None = None,
) -> int:
    """Persist chunks WITHOUT generating embeddings (P0.2).

    Creates chunks with ``embedding=NULL`` and ``needs_reembedding=True``
    so the OCR worker never calls the embedding provider. A dedicated
    embedding task will pick these up later.

    Returns the number of chunks created.
    """
    from app.services.document_processing_core import sanitize_text_for_database

    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))

    chunk_payloads: list[tuple[int, str, str, int, str]] = []
    for page_number, page_text in page_texts:
        clean_text = sanitize_text_for_database(page_text)
        for chunk in build_chunks(
            clean_text,
            max_words=settings.embedding_chunk_max_words,
            overlap_words=settings.embedding_chunk_overlap_words,
            respect_tables=settings.embedding_chunk_respect_tables,
            respect_headings=settings.embedding_chunk_respect_headings,
        ):
            chunk_text = chunk.text
            token_count = chunk.token_count
            chunk_type = chunk.chunk_type
            embedding_text = embedding_text_with_metadata(
                chunk_text,
                document_type=document_type,
                filename=original_filename,
                page_number=page_number,
            )
            chunk_payloads.append(
                (page_number, chunk_text, embedding_text, token_count, chunk_type)
            )

    count = 0
    for page_number, chunk_text, _embedding_text, token_count, chunk_type in chunk_payloads:
        chunk = DocumentChunk(
            document_id=document_id,
            page_number=page_number,
            chunk_text=chunk_text,
            embedding=None,
            embedding_provider_used=None,
            embedding_fallback=False,
            needs_reembedding=True,
            token_count=token_count,
        )
        chunk.chunk_type = chunk_type
        chunk.embedding_model_version = settings.embedding_model
        db.add(chunk)
        count += 1

    db.flush()
    return count


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
    new_chunks = prepare_document_chunks(
        document_id,
        page_texts,
        document_type=document.document_type,
        original_filename=document.original_filename,
    )

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

    document_embedding = apply_document_embedding(db, document_id, page_texts)

    # Keep the document-level retrieval state in sync with the chunks we have
    # just rebuilt.  The normal asynchronous embedding task does this after a
    # successful run, but this admin re-embed path used to leave every document
    # marked ``semantic_search_ready=False`` even when all of its chunks had
    # vectors.  That made successful manual recovery invisible to semantic
    # retrieval.
    has_chunks = bool(new_chunks)
    chunks_ready = has_chunks and all(
        chunk.embedding is not None and not chunk.needs_reembedding for chunk in new_chunks
    )
    document.needs_reembedding = has_chunks and not chunks_ready
    document.semantic_search_ready = chunks_ready
    if chunks_ready:
        document.pipeline_stage = "searchable"
    elif has_chunks:
        document.pipeline_stage = "embedding_pending"
    else:
        # Some valid inputs (for example an image with no extracted text)
        # intentionally produce no chunks.  They have nothing to retry, so
        # never leave them stranded in ``embedding_pending``.
        document.needs_reembedding = False
        document.semantic_search_ready = False
        document.pipeline_stage = "fully_processed"

    db.commit()

    provider = settings.embedding_provider
    return {
        "document_id": document_id,
        "chunks_updated": updated,
        "chunks_with_embedding": sum(1 for c in new_chunks if c.embedding is not None),
        "chunks_needing_reembedding": sum(1 for c in new_chunks if c.needs_reembedding),
        "document_embedding": document_embedding,
        "provider": provider,
    }
