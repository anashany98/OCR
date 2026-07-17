# Plan: Integración de Docling en el Pipeline de Procesamiento

> Estado: Borrador — pendiente de implementación.
> Fecha: 2026-07-16
> Relacionado: `PLAN_IMPLEMENTACION_OVISOCR2.md` (mismo patrón de servicio externo opt-in).

## Decisiones confirmadas

| Dimensión | Decisión |
|---|---|
| **Alcance de formatos** | Solo PDF (donde Docling aporta más valor: layout, tablas, reading order) |
| **Estrategia** | Opt-in por config (`pdf_parser="docling"` \| `"legacy"`). Convive con el parser PDF actual, permite A/B testing y rollback inmediato |
| **OCR interno** | `do_ocr=False` en Docling; las páginas escaneadas se renderizan y pasan al cascade OCR existente (Tesseract→PaddleOCR→VLM). Mantiene la inversión en control de calidad |
| **Dependencias** | Servicio Docling separado (`docling-serve` en su contenedor, API HTTP). El backend lo llama vía `httpx` como ya hace con NuExtract/OvisOCR2. **No se añade torch al backend** |

---

## Arquitectura

```
                    ┌─────────────────────────────────────────────┐
                    │  router.parse_document(path, ...)           │
                    │  si extension == ".pdf":                    │
                    │     if settings.pdf_parser == "docling"     │
  ────────►         │         and DoclingClient.is_configured():  │ ───► parse_pdf_docling() ──► contenedor docling-serve (HTTP)
                    │     else: parse_pdf()  [legacy, sin cambios] │
                    └─────────────────────────────────────────────┘
```

El parser `parse_pdf_docling` produce un `ExtractedDocument` **idénticamente compatible** al de `parse_pdf` (mismos metadatos, naming `page_N.jpg`, `block_type`s, `ocr_content_kind`). El resto del pipeline (clasificación, business extraction, chunking, embeddings, hyperextract) no se modifica.

**Flujo interno de `parse_pdf_docling`:**

1. Llama a `classify_content(path, folder_hint)` (igual que el legacy) — preserva el content routing.
2. Sube el PDF a `docling-serve` con `do_ocr=False`, `to_formats=["md","json"]`, `image_export_mode="referenced"`, `table_mode="accurate"`.
3. Para cada página de la respuesta JSON de Docling:
   - Si Docling reporta texto digital (≥30 chars en `json_content`): construye `ExtractedPage` con `ocr_content_kind="native_text"`, `ocr_engine="docling"`, `ocr_confidence=1.0`, y `ExtractedBlock` por cada item del DoclingDocument (mapeando tipos: `title`→`text`, `table`→`table` con markdown, `text`→`text`, `picture`→`figure`).
   - Si la página es escaneada (texto nativo < 30 chars): la renderiza con PyMuPDF a `page_N.jpg` (mismo DPI ladder que el legacy) y la pasa al `ocr_engine.extract()` del cascade. Construye el `ExtractedPage` con los metadatos del OCR.
4. Respeta `settings.max_pdf_pages` y el vision fallback (`_maybe_vision_table`).

---

## Archivos a crear/modificar

### 1. NUEVO: `app/services/docling_client.py` (~250 líneas)
Cliente HTTP síncrono para `docling-serve`, clonando el patrón robusto de `app/ocr/ovisocr2.py`:

- `@dataclass(frozen=True) DoclingConfig` con `from_settings()`.
- Clase `DoclingClient`:
  - `httpx.Client` reusable con `httpx.Timeout` granular (connect/read/write/pool).
  - `CircuitBreaker(fail_max, reset_timeout, name="docling")` por-instancia (de `app/services/circuit_breaker.py`).
  - `_post_with_retry()`: reintenta 5xx y `httpx.TransportError`, **no** 4xx (backoff fijo 0.2s, 2 intentos).
  - Subida **multipart** (`/v1/convert/file`, campo `files`), streaming de la respuesta con tope `max_response_bytes` (anti-OOM).
  - `is_configured() -> bool` (patrón `settings.docling_enabled and self.endpoint`).
  - `convert_pdf(path, *, do_ocr, to_formats, image_export_mode, table_mode) -> dict` (devuelve el JSON de respuesta).
- Jerarquía de excepciones: `DoclingError(RuntimeError)`, `DoclingNotEligible(DoclingError)`, `DoclingTimeout(DoclingError)`.
- Métricas: `track_docling_request(status, reason, elapsed)` (extender `app/services/metrics/ocr.py`).
- **Depende solo de `httpx`** (ya en requirements.txt). No se añade `docling` al backend.

### 2. NUEVO: `app/parsers/pdf_docling.py` (~350 líneas)
Parser que orquesta Docling + cascade OCR. Estructura paralela a `app/parsers/pdf.py`:

- `parse_pdf_docling(path, output_dir, ocr_engine, folder_hint) -> ExtractedDocument`.
- Reutiliza helpers existentes de `pdf.py` factorizándolos si es necesario:
  - `_render_page_to_image` (ya existe en `pdf.py:29`) — importar o mover a un `_pdf_rendering.py` compartido.
  - `_maybe_vision_table`, `_ocr_with_dpi_ladder` — importar de `pdf.py`.
  - Check de `max_pdf_pages` (abre con fitz para contar páginas antes de llamar a Docling).
- Mapeo DoclingDocument → ExtractedBlock:

  | Docling `label` | `block_type` | Notas |
  |---|---|---|
  | `title`, `section_header` | `text` | Prefijo con `# ` para chunking |
  | `text`, `paragraph`, `caption` | `text` | |
  | `table` | `table` | Serializa a markdown pipe-table (Docling ya lo da en `md_content`) |
  | `picture`, `figure` | `figure` | |
  | `list_item` | `text` | |
  | `page_header`/`page_footer` | `header`/`footer` | |

  - `bbox` se preserva (Docling da `bbox` en coordenadas de página).
- Manejo de errores: si `DoclingClient` lanza `DoclingError` o el circuit breaker está abierto → **fallback automático a `parse_pdf` legacy** con un log warning (degradación graceful, el documento no se pierde).

### 3. MODIFICAR: `app/parsers/router.py`
Añadir la rama Docling antes de la rama `.pdf` legacy:

```python
if extension == ".pdf":
    if settings.pdf_parser == "docling" and DoclingClient.is_configured():
        try:
            return parse_pdf_docling(path, output_dir, ocr_engine, folder_hint=folder_hint)
        except DoclingError as exc:
            logger.warning("Docling failed (%s); falling back to legacy PDF parser", exc)
    return parse_pdf(path, output_dir, ocr_engine, folder_hint=folder_hint)
```

### 4. MODIFICAR: `app/core/config.py`
Añadir bloque `docling_*` (junto a las secciones `ovisocr2_*`/`nuextract_*` existentes):

```python
# Docling (opt-in PDF parser, external service)
docling_enabled: bool = False
docling_endpoint: str = "http://docling-serve:5001"
docling_api_key: str = ""
docling_timeout_seconds: float = 300.0
docling_connect_timeout_seconds: float = 10.0
docling_max_response_bytes: int = 67_108_864  # 64 MB
docling_circuit_failures: int = 3
docling_circuit_reset_seconds: float = 120.0
docling_table_mode: str = "accurate"  # "fast" | "accurate"
docling_image_export_mode: str = "referenced"  # "placeholder"|"embedded"|"referenced"
docling_model_version: str = ""  # para re-OCR sweep futuro
pdf_parser: str = "legacy"  # "legacy" | "docling"
```

Más un `@model_validator(mode="after") _validate_docling_settings` (copia del patrón de OvisOCR2): valida endpoint `http(s)://`, timeouts > 0, `table_mode` en `{fast,accurate}`, `image_export_mode` en el enum.

### 5. MODIFICAR: `docker-compose.yml`
Añadir servicio `docling-serve` (perfil opt-in), copiando el patrón de `ovisocr2`:

```yaml
docling-serve:
  profiles: ["docling"]
  image: ghcr.io/docling-project/docling-serve:latest   # o build: ./services/docling-serve
  restart: unless-stopped
  mem_limit: ${DOCLING_MEM_LIMIT:-8g}
  shm_size: ${DOCLING_SHM_SIZE:-2g}
  environment:
    - DOCLING_SERVE_API_KEY=${DOCLING_API_KEY:-}
    - HF_HOME=/models/huggingface
  runtime: nvidia           # GPU para layout/tables (más rápido)
  deploy:
    resources:
      reservations:
        devices: [{driver: nvidia, device_ids: ["${DOCLING_GPU_DEVICE:-0}"], capabilities: [gpu]}]
  volumes:
    - docling_model_cache:/models/huggingface
  networks:
    - docling_internal
  healthcheck:
    test: ["CMD-SHELL", "python3 -c \"import urllib.request; r=urllib.request.urlopen('http://localhost:5001/health'); exit(0 if r.status==200 else 1)\""]
    interval: 30s
    timeout: 10s
    retries: 5
    start_period: 300s
```

- Declarar red `docling_internal: {internal: true}` + `docling_egress: {internal: false}`.
- Añadir `docling_internal` a las `networks:` de los workers OCR (`worker-heavy`, `worker-heavy-gpu-*`) para que puedan llamarlo; **no** al backend/frontend.
- Volumen `docling_model_cache` en el bloque raíz.

### 6. MODIFICAR: `app/services/metrics/ocr.py`
Añadir contadores: `track_docling_request(status, reason, elapsed)`, `track_docling_pages(digital, scanned)`. Seguir el patrón existente (`track_ovisocr2_request`).

### 7. MODIFICAR: `.env.example` y `.env.production.example`
Añadir sección `# Docling (opt-in PDF parser)` con todas las variables `DOCLING_*` y `PDF_PARSER=legacy` (default off).

### 8. NUEVO: `services/docling-serve/Dockerfile` (opcional)
Solo si se quiere customizar la imagen (ej: pin de versión, modelos pre-cargados). Si no, usar la imagen oficial `ghcr.io/docling-project/docling-serve:latest`.

---

## Contrato de compatibilidad (lo que garantiza que el resto funciona)

El `ExtractedDocument` producido cumple con el contrato que el pipeline exige (verificado contra `document_processing_core.py` y consumers):

| Campo | Valor para página digital | Valor para página escaneada |
|---|---|---|
| `page_number` | 1-based (igual que legacy) | 1-based |
| `text` | texto de Docling (md + tablas) | texto del cascade OCR |
| `width`/`height` | puntos PDF (de Docling `page.size` o fitz) | puntos PDF (fitz) |
| `image_path` | `None` (como el legacy) | `str(output_dir / "page_N.jpg")` |
| `ocr_confidence` | `1.0` | del cascade OCR |
| `ocr_content_kind` | `"native_text"` | `"ocr"` |
| `ocr_engine` | `"docling"` | nombre del motor cascade |
| `blocks[].block_type` | `text`/`table`/`figure`/`header`/`footer` | del cascade / `text` |
| `blocks[].bbox` | de Docling (coordenadas de página) | de OCR / página completa |

Esto alimenta sin cambios a: clasificación (reglas sobre `text`), business extraction (regex + clustering layout-aware con `bbox`), chunking, embeddings, hyperextract, VLM table extraction (vía `image_path`).

---

## Plan de implementación por fases

### Fase 1 — Fundación (sin tocar el pipeline en producción)
1. Añadir settings `docling_*` + `pdf_parser` en `config.py` con validador.
2. Crear `app/services/docling_client.py` (cliente HTTP + breaker).
3. Añadir métricas en `metrics/ocr.py`.
4. **Tests unitarios** del cliente (mock httpx, breaker abierto/cerrado, timeout, 4xx vs 5xx).

### Fase 2 — Parser
5. Factorizar helpers de `pdf.py` que se reutilizarán (`_render_page_to_image`, `_maybe_vision_table`, check de páginas) — mover a `app/parsers/_pdf_helpers.py` o exponer vía import.
6. Crear `app/parsers/pdf_docling.py` con el mapeo DoclingDocument → ExtractedDocument.
7. **Tests unitarios** del parser (mock del cliente Docling con JSON fixture, verificación del contrato ExtractedDocument, fallback a legacy).

### Fase 3 — Cableado
8. Modificar `router.py` para la rama opt-in + fallback.
9. **Test de integración**: PDF digital, PDF escaneado, PDF mixto, PDF con tablas — comparar output vs legacy.

### Fase 4 — Infraestructura
10. Añadir servicio `docling-serve` en `docker-compose.yml` + redes + volumen.
11. Añadir variables en `.env.example`.

### Fase 5 — Documentación y verificación
12. Documentar en este mismo archivo (o README de parsers): cómo activar, requisitos, trade-offs, troubleshooting.
13. Ejecutar `pytest` completo y `ruff`/`mypy` para garantizar que nada se rompe.

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Docling-serve caído o lento | Circuit breaker (3 fallos → open 120s) + fallback automático a `parse_pdf` legacy. El documento siempre se procesa. |
| Respuesta JSON enorme (OOM) | `max_response_bytes` con streaming y abort. |
| Calidad de tablas inferior a pdfplumber en algún caso | `table_mode="accurate"` por defecto; se puede comparar vía A/B (flag `pdf_parser`) sin migrar todo. |
| Latencia añadida (round-trip HTTP) | Solo para PDFs; el legacy queda para imágenes/excel/docx. Timeout de 300s cubre documentos grandes. El cascade OCR ya es el cuello dominante. |
| Bug conocido de docling-serve (#567: `ocr_engine` ignorado en `/v1/convert/file`) | **No nos afecta**: usamos `do_ocr=False` y delegamos el OCR al cascade propio. Docling solo hace layout + texto digital + tablas. |
| Divergencia de `bbox` (coordenadas Docling vs puntos PDF) | Normalizar en el mapeo: Docling usa píxeles o puntos según backend; verificar y convertir a puntos PDF para que `table_extraction.py` funcione. |

---

## Lo que NO se hace en este plan
- No se modifica el cascade OCR, content_router, clasificación, ni ningún extractor de negocio.
- No se añade `docling`/`torch`/`transformers` a `requirements.txt` del backend.
- No se reemplaza el parser PDF legacy (queda como default y como fallback).
- No se tocan los parsers de DOCX/Excel/MSG/imágenes/CAD.
- No se añade healthcheck de Docling al endpoint `/health` del backend (se infiere del flag + healthcheck de Docker, como hace OvisOCR2).

---

## Verificación de éxito
- `PDF_PARSER=docling` procesa un PDF digital y el `ExtractedDocument` pasa el mismo test de contrato que el legacy.
- Con `docling-serve` caído, el mismo PDF se procesa vía fallback legacy sin error 500.
- `PDF_PARSER=legacy` (default) deja todo el comportamiento actual sin cambios.
- `pytest` pasa y `ruff check`/`mypy` limpios.
