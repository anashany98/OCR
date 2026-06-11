# Plan de Optimización Docu-Intel

## Objetivo
Optimizar el rendimiento de OCR, API y búsqueda vectorial en Docu-Intel.

## Contexto Actual
- OCR: PaddleOCR con GPU workers
- Embeddings: Ollama (nomic-embed-text:v1.5) en puerto 11434
- Vector Store: pgvector (PostgreSQL)
- API: FastAPI con workers Celery
- Cache: Redis (ya disponible en docker-compose)

---

## Estado: 8/8 Completadas

| # | Tarea | Estado | Archivo | Cambio |
|---|-------|--------|---------|--------|
| 1 | HNSW Index | ✅ COMPLETADA | SQL | Índice `ix_document_chunks_embedding_hnsw` creado |
| 2 | Redis Caching | ✅ COMPLETADA | - | Ya estaba implementado (EMBEDDING_CACHE_TTL=3600) |
| 3 | OCR Cache | ✅ COMPLETADA | `document_service.py` | `register_existing_file()` ahora retorna documento existente si status es `processed` o `needs_review` |
| 4 | OCR Batching | ✅ COMPLETADA | `pdf.py` | Fast path para PDFs digitales con `is_digital_pdf()` - skip OCR si >90% texto digital |
| 5 | Connection Pool | ✅ COMPLETADA | `session.py` | `pool_size=20`, `pool_recycle=3600` |
| 6 | Tesseract Fallback | ✅ COMPLETADA | `pdf.py` | Integrado en task 4 - `is_digital_pdf()` detecta y salta OCR |
| 7 | Hybrid Search | ✅ COMPLETADA | `search_service.py` | Ya estaba implementado: `search_hybrid()` combina text + semantic |
| 8 | Monitoring | ✅ COMPLETADA | `metrics.py`, `main.py` | Endpoint `/metrics` con Prometheus format |

---

## Detalle de Cambios

### Tarea 1: HNSW Index ✅
Índice creado directamente en PostgreSQL:
```sql
CREATE INDEX ix_document_chunks_embedding_hnsw
ON document_chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

### Tarea 2: Redis Caching ✅
Ya estaba implementado en `embeddings.py`:
- Cache key: `embedding:{md5(content)}`
- TTL: 3600 segundos (1 hora)

### Tarea 3: OCR Cache (Re-upload) ✅
**Archivo:** `backend/app/services/document_service.py` (línea ~98)

**Cambio:**
```python
if existing:
    # If existing document is fully processed, return it directly (skip OCR)
    if existing.status in {"processed", "needs_review"}:
        return existing, None
    # Otherwise mark as duplicate
    status = "duplicate"
    duplicate_of_document_id = existing.id
    stored_filename = existing.stored_filename
```

### Tarea 4: OCR Batching - Fast Path PDFs Digitales ✅
**Archivo:** `backend/app/parsers/pdf.py`

**Nueva función:**
```python
def is_digital_pdf(path: Path) -> bool:
    """Check if PDF has sufficient digital text content (>90% text pages)."""
    import fitz
    with fitz.open(path) as pdf:
        text_pages = 0
        total_pages = len(pdf)
        for page in pdf:
            text = page.get_text("text").strip()
            if len(text) >= 30:
                text_pages += 1
        return text_pages / total_pages > 0.9 if total_pages > 0 else False
```

**Cambio en `parse_pdf()`:** Al inicio, si `is_digital_pdf(path)` returns True, extrae texto directamente sin OCR.

### Tarea 5: Connection Pool Optimization ✅
**Archivo:** `backend/app/database/session.py`

**Cambio:**
```python
# Antes:
engine = create_engine(settings.database_url, pool_pre_ping=True)

# Después:
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=20, pool_recycle=3600)
```

### Tarea 6: Tesseract Fallback para PDFs Digitales ✅
Implementado en la tarea 4 con `is_digital_pdf()`.

### Tarea 7: Hybrid Search (BM25 + Vector) ✅
Ya estaba implementado en `backend/app/services/search_service.py`:
- `search_hybrid()` combina `search_text()` + `search_semantic()`
- `merge_hybrid_results()` combina scores: `0.7 * semantic + 0.3 * text`

### Tarea 8: Monitoring Metrics ✅
**Nuevo archivo:** `backend/app/services/metrics.py`

**Métricas rastreadas:**
- `docuintel_ocr_duration_seconds_total` / `docuintel_ocr_requests_total`
- `docuintel_embedding_latency_seconds_total` / `docuintel_embedding_requests_total`
- `docuintel_search_latency_seconds_total` / `docuintel_search_requests_total`
- `docuintel_cache_hits_total` / `docuintel_cache_misses_total`

**Endpoint:** `GET /metrics` (Prometheus text format)

**Integración:** `main.py` ahora llama `register_metrics_endpoint(app)`

**Instrumentación:**
- `embeddings.py`: track_embedding_latency(), track_cache_hit(), track_cache_miss()
- `search_service.py`: track_search_latency() para search_text, search_semantic, search_hybrid
- `paddle.py`: track_ocr_duration() en extract()

---

## Archivos Modificados

| Archivo | Cambios |
|---------|---------|
| `backend/app/services/document_service.py` | OCR cache (línea ~98) |
| `backend/app/parsers/pdf.py` | is_digital_pdf() + fast path |
| `backend/app/database/session.py` | pool_size=20 |
| `backend/app/services/search_service.py` | track_search_latency() |
| `backend/app/services/embeddings.py` | track_embedding_latency(), cache metrics |
| `backend/app/ocr/paddle.py` | track_ocr_duration() |
| `backend/app/services/metrics.py` | NUEVO - métricas + endpoint |
| `backend/app/main.py` | register_metrics_endpoint() |

---

## Notas

- Todas las tareas completadas sin dependencias externas adicionales
- No se instaló prometheus_client - métricas in-memory para simplicidad
- Para producción, considerar usar `prometheus_client` con Pushgateway

**Fecha:** 2026-05-21