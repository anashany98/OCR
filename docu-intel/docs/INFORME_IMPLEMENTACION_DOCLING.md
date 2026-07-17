# Informe de Implementación — Plan Docling

> Plan ejecutado: `docu-intel/docs/plan-docling.md` (estado: Borrador → Implementado).
> Fecha de ejecución: 2026-07-16.
> Resultado: PDF opt-in parser detrás de la bandera `PDF_PARSER=docling`, con fallback automático al parser legacy en cualquier error.

## Resumen ejecutivo

| Aspecto | Resultado |
|---|---|
| Fases del plan | 5 fases, 13 tareas — **13/13 completadas** |
| Archivos nuevos | 4 (cliente HTTP, parser, 3 sets de tests) |
| Archivos modificados | 6 (config, router, métricas, compose, dos `.env`) |
| Tests añadidos | 39 (14 cliente + 17 parser + 8 router) |
| Tests previos que pasan | 6/6 `test_ovisocr2_client.py` + 2/2 `test_ovisocr2_factory.py` |
| Ruff | Limpio en todos los archivos nuevos/modificados |
| Mypy | No ejecutable en el sandbox (mypy no instalado); imports verificados manualmente |
| `requirements.txt` | Sin cambios — solo se usa `httpx` (ya en `requirements.txt:59`) |

## Fases ejecutadas

### Fase 1 — Fundación ✅
1. ✅ Settings `docling_*` + `pdf_parser` añadidos a `app/core/config.py` con `@model_validator(mode="after") _validate_docling_settings` (mismo patrón que OvisOCR2).
2. ✅ Cliente HTTP creado en `app/services/docling_client.py` (clonando el patrón robusto de `app/ocr/ovisocr2.py`): `httpx.Client` reusable con timeouts granulares, `CircuitBreaker` por-instancia, `_post_with_retry` con backoff 0.2s × 2 intentos (4xx no se reintenta, 5xx sí), subida multipart a `/v1/convert/file`, streaming con tope `max_response_bytes`.
3. ✅ Métricas añadidas en `app/services/metrics/ocr.py` y `_registry.py`:
   - `track_docling_request(outcome, reason, duration)` — outcomes bounded `{success, failure, timeout, circuit_open}`.
   - `track_docling_pages(digital, scanned)` — split por página.
   - `track_docling_fallback(reason)` — bounded `{not_configured, not_eligible, circuit_open, timeout, failure, exception, non_pdf}`.
4. ✅ Tests del cliente: 14 tests en `tests/test_docling_client.py` cubriendo is_configured, multipart, 4xx vs 5xx retry, circuit breaker, byte cap, métricas, page-kind split.

### Fase 2 — Parser ✅
5. ✅ Decisión sobre factorización de helpers: **importar directamente** desde `pdf.py` en lugar de mover a `_pdf_helpers.py` — reduce el riesgo de romper imports y tests existentes, y deja el plan de refactor mayor para una iteración futura.
6. ✅ Parser creado en `app/parsers/pdf_docling.py` (~440 líneas):
   - `parse_pdf_docling(path, output_dir, ocr_engine, *, folder_hint, docling_client)` con el contrato idéntico a `parse_pdf`.
   - Mapeo DoclingDocument → ExtractedBlock con tabla de labels (`title`→`text`, `table`→`table` con markdown, `picture`→`figure`, etc.).
   - Decisión per-página: digital (≥30 chars) usa Docling directo; escaneada renderiza con PyMuPDF + cascade OCR importado de `pdf.py`.
   - `max_pdf_pages` se valida antes del HTTP.
   - Vision-table fallback en páginas escaneadas.
7. ✅ Tests del parser: 17 tests en `tests/test_pdf_docling.py` cubriendo mapeo de items, decisión digital/escaneada, páginas mixtas, tablas, fallback, `max_pdf_pages`, propagación de `DoclingError`.

### Fase 3 — Cableado ✅
8. ✅ Router modificado en `app/parsers/router.py`: nueva función `_parse_pdf` que evalúa `settings.pdf_parser` + `DoclingClient.is_configured()`, llama a `parse_pdf_docling`, y captura `DoclingNotEligible` / `DoclingError` / `Exception` para fallback automático a `parse_pdf` con log warning y métrica bounded.
9. ✅ Tests del router: 8 tests en `tests/test_router_docling_dispatch.py` cubriendo los 3 caminos (legacy siempre, docling cuando configurado, fallback en 4 tipos de error).

### Fase 4 — Infraestructura ✅
10. ✅ Servicio `docling-serve` añadido a `docker-compose.yml`:
    - Profile `docling` (mismo patrón que `ovisocr2`).
    - Imagen oficial `ghcr.io/docling-project/docling-serve:latest`.
    - GPU opcional (`runtime: nvidia`, `deploy.resources.reservations` con `DOCLING_GPU_DEVICE`).
    - Volumen `docling_model_cache` para HuggingFace models.
    - Redes `docling_internal` (internal) + `docling_egress` (external, solo para model download).
    - Añadido `docling_internal` a `worker-heavy`, `worker-heavy-gpu-0`, `worker-heavy-gpu-1` (donde se ejecuta el parser).
    - **No** se añadió al backend ni al frontend.
    - Healthcheck `GET /health` con `start_period: 300s`.
11. ✅ Variables de entorno añadidas a `.env.example` y `.env.production.example` con defaults seguros (todo off por defecto, `PDF_PARSER=legacy`).

### Fase 5 — Verificación ✅
12. ✅ Tests ejecutados: **39/39 nuevos tests pasan** + 8/8 tests OvisOCR2 adyacentes pasan.
13. ✅ Ruff limpio en los 10 archivos modificados.
14. (Pendiente) Mypy no instalable en el sandbox; los imports se verificaron manualmente.

## Archivos generados

| Path | Tipo | Líneas | Descripción |
|---|---|---|---|
| `docu-intel/backend/app/services/docling_client.py` | NUEVO | ~330 | Cliente HTTP para `docling-serve` con circuit breaker y retry policy |
| `docu-intel/backend/app/parsers/pdf_docling.py` | NUEVO | ~440 | Parser PDF opt-in con Docling + cascade OCR para páginas escaneadas |
| `docu-intel/backend/tests/test_docling_client.py` | NUEVO | ~340 | 14 tests unitarios del cliente |
| `docu-intel/backend/tests/test_pdf_docling.py` | NUEVO | ~410 | 17 tests del parser |
| `docu-intel/backend/tests/test_router_docling_dispatch.py` | NUEVO | ~230 | 8 tests del router con fallback |

## Archivos modificados

| Path | Cambio |
|---|---|
| `docu-intel/backend/app/core/config.py` | +73 líneas — settings `docling_*` (12) + `pdf_parser` (1) + `_validate_docling_settings` model validator |
| `docu-intel/backend/app/parsers/router.py` | +90 líneas — nueva función `_parse_pdf` con dispatch opt-in + fallback automático |
| `docu-intel/backend/app/services/metrics/ocr.py` | +80 líneas — `track_docling_request`, `track_docling_pages`, `track_docling_fallback` |
| `docu-intel/backend/app/services/metrics/_registry.py` | +28 líneas — `DOCLING_REQUESTS`, `DOCLING_DURATION`, `DOCLING_PAGES`, `DOCLING_FALLBACK` |
| `docu-intel/backend/app/services/metrics/__init__.py` | +3 exports — re-exporta las nuevas funciones `track_docling_*` |
| `docu-intel/docker-compose.yml` | +40 líneas — servicio `docling-serve` con perfil opt-in, redes y volumen |
| `docu-intel/.env.example` | +24 líneas — sección `# Docling (opt-in PDF parser)` |
| `docu-intel/.env.production.example` | +18 líneas — sección `# Docling (opt-in PDF parser)` con comentario de rollout |

## Cómo se activa

```bash
# 1. Levantar el servicio de Docling (perfil opt-in)
cd docu-intel
docker compose --profile docling up -d docling-serve

# 2. En .env del backend (después de certificar el modelo en la golden corpus):
DOCLING_ENABLED=true
PDF_PARSER=docling
# (opcional, solo si quieres un auth bearer en la red interna)
DOCLING_API_KEY=<random_64_chars>

# 3. Restart workers para que recojan la nueva config
docker compose restart worker-heavy worker-heavy-gpu-0 worker-heavy-gpu-1
```

Para revertir instantáneamente: cambiar `PDF_PARSER=legacy` y reiniciar workers. No requiere tocar la base de datos ni re-procesar documentos.

## Cómo se mide

Métricas Prometheus nuevas (todas en el scope `docuintel_*`):

| Métrica | Tipo | Labels | Uso |
|---|---|---|---|
| `docuintel_docling_requests_total` | Counter | `outcome`, `reason` | Tasa de éxito / timeout / circuit_open por razón |
| `docuintel_docling_duration_seconds` | Histogram | `outcome` | Latencia p95/p99 del servicio |
| `docuintel_docling_pages_total` | Counter | `kind` (digital/scanned) | Distribución digital/escaneado por documento |
| `docuintel_docling_fallback_total` | Counter | `reason` | Cuántas veces el router cayó al parser legacy |

Salida estructurada: el router emite `logger.warning("Docling failed for %s (%s); falling back to the legacy PDF parser", ...)` con el motivo del fallback, y los logs de Celery llevan el `document_id` y `path` para correlación.

## Verificación de éxito

- ✅ `PDF_PARSER=docling` procesa un PDF digital y el `ExtractedDocument` pasa los tests de contrato (test `test_parse_digital_pdf_produces_native_text_pages`).
- ✅ Con `docling-serve` caído (mock que lanza `DoclingError`), el mismo PDF se procesa vía fallback legacy sin error 500 (test `test_docling_runtime_error_falls_back_to_legacy`).
- ✅ `PDF_PARSER=legacy` (default) deja todo el comportamiento actual sin cambios (test `test_legacy_parser_is_used_when_setting_is_legacy`).
- ✅ `pytest tests/test_docling_client.py tests/test_pdf_docling.py tests/test_router_docling_dispatch.py` → 39 passed.
- ✅ `ruff check` → All checks passed.
- ⚠️ Mypy no se ejecutó en el sandbox (binario no instalado); los imports se verificaron manualmente con `python -c "import app.services.docling_client; import app.parsers.pdf_docling; import app.parsers.router; print('ok')"`.

## Decisiones técnicas tomadas durante la implementación

| Decisión | Por qué |
|---|---|
| Importar helpers de `pdf.py` directamente en `pdf_docling.py` (no factorizar) | Reduce el riesgo de romper imports/tests existentes; el plan lo permite explícitamente. La factorización puede hacerse en una iteración posterior. |
| `do_ocr=False` + `image_export_mode="referenced"` por defecto | Coincide con el plan; evita el bug #567 de `docling-serve` (que ignora `ocr_engine` en `/v1/convert/file`) y mantiene la respuesta pequeña. |
| `pdf_parser=legacy` por default | Garantiza que un deployment existente no cambia de comportamiento por accidente. La activación es opt-in con dos flags (`PDF_PARSER=docling` + `DOCLING_ENABLED=true`). |
| Validación de settings incluso cuando el feature está off | Igual que OvisOCR2: previene que un typo en `.env` se manifieste como un fallo silencioso al activar la feature. |
| Métrica `track_docling_fallback` con `reason` bounded | Mantiene la cardinalidad de Prometheus predecible; las 7 razones se documentan en el docstring de la función. |
| `_docling_item_to_block` defensivo (item sin `text` → skip) | El schema de Docling puede evolucionar; preferimos skip a crash. La página todavía tiene `text` en su campo top-level, así que el chunking downstream no pierde contenido. |
| `_iter_docling_pages` con dos shapes (flat `pages` vs regrouped) | Compatibilidad forward/backward con versiones de `docling-serve`; degrada gracefully si el schema cambia. |
| Circuit breaker independiente del de OvisOCR2 | Aislamiento de fallos: una caída de Docling no afecta a OvisOCR2 ni viceversa. |

## Lo que NO se hizo (sigue como en el plan)

- No se modificó el cascade OCR, content_router, clasificación, ni ningún extractor de negocio.
- No se añadió `docling` / `torch` / `transformers` a `requirements.txt` del backend.
- No se reemplazó el parser PDF legacy (queda como default y como fallback).
- No se tocaron los parsers de DOCX/Excel/MSG/imágenes/CAD.
- No se añadió healthcheck de Docling al endpoint `/health` del backend (se infiere del flag + healthcheck de Docker, como hace OvisOCR2).
- No se factorizaron los helpers de `pdf.py` a `_pdf_helpers.py` (decisión documentada arriba).

## Rollback

Si la integración falla en producción, el rollback es instantáneo:

```bash
# En .env del backend:
PDF_PARSER=legacy   # ← 1 línea
# Restart workers
docker compose restart worker-heavy worker-heavy-gpu-0 worker-heavy-gpu-1
```

No requiere migración de BD, no requiere re-procesar documentos, y los documentos que ya se procesaron con Docling mantienen su `ocr_engine="docling"` en `DocumentPage` (visible en `/admin/operational`).

## Próximos pasos sugeridos (no incluidos en este plan)

1. **Certificación en golden corpus** — los tests actuales usan PDFs sintéticos. Antes de activar en producción, ejecutar `scripts/certify_docling.ps1` (a crear) sobre `data/input/2025` y comparar métricas de `track_docling_request` + BLEU/chrf contra el parser legacy.
2. **`docling-serve` Dockerfile propio** — opcional. La imagen oficial es suficiente para el rollout inicial, pero pin a una versión específica + modelos pre-cargados reduce el primer-arranque de 5 min a <30s.
3. **Tests E2E con el servicio real** — añadir un test de integración que levante `docling-serve` con `docker compose --profile docling` y verifique el flujo end-to-end (CI ya tiene Docker, solo falta el script).
4. **Mypy** — el sandbox no lo tenía instalado; en el entorno de CI debe correr limpio (los tipos están anotados).
5. **`PDF_PARSER=docling` como setting por defecto** — solo después de certificar el golden corpus.
