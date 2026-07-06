# Análisis profundo del proyecto Docu-Intel — Mejoras y soluciones

> 📌 **Análisis exhaustivo** de toda la base de código (backend + frontend + infra),
> realizado sobre la rama `feature/nuextract3-integration` a 2026-07-02. Cubre:
> OCR, IA conversacional, recuperación/búsqueda, extracción de negocio, planos,
> infraestructura, frontend y seguridad.
>
> Para cada hallazgo: severidad 🔴/🟠/🟡/⚪, estado (✅ ya arreglado / ⚠️ pendiente),
> `file:line`, problema, solución y impacto.
>
> **Lectura recomendada:** empezar por el "Resumen ejecutivo", luego ir a la
> sección del bloque que interese. Las tareas marcadas **⚠️ HECHO** ya están en
> commits anteriores (`bdfd90b`, `68774ce`, `44536ee`).

---

## Tabla de contenidos

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [Bloque OCR / Pipeline](#2-bloque-ocr--pipeline)
3. [Bloque IA / Conversacional](#3-bloque-ia--conversacional)
4. [Bloque Recuperación / Búsqueda](#4-bloque-recuperación--búsqueda)
5. [Bloque Extracción de negocio / Planos](#5-bloque-extracción-de-negocio--planos)
6. [Bloque Infraestructura / Observabilidad](#6-bloque-infraestructura--observabilidad)
7. [Bloque Frontend](#7-bloque-frontend)
8. [Lo que ya está bien hecho (no tocar)](#8-lo-que-ya-está-bien-hecho-no-tocar)
9. [Plan de ejecución priorizado](#9-plan-de-ejecución-priorizado)

---

## 1. Resumen ejecutivo

El proyecto está **sólido en arquitectura general**: cascada OCR multi-tier, RRF
híbrido, reranker cross-encoder, chunking estructural, circuit breakers, validación
anti-alucinación, magic bytes en uploads, backups scriptados. Mucho de lo que un
brief inicial (`AGENTS.md`) marcaba como pendiente **ya está implementado**.

Los problemas reales se concentran en **4 áreas**, ordenadas por impacto:

| Área | Problema dominante | Severidad |
|---|---|---|
| **Extracción de factura** | Base/IVA/NIF/nº pedido se calculan y se descartan al persistir (modelo sin columnas). No hay agregaciones SQL ("suma de facturas de mayo"). | 🔴 |
| **Validación de respuestas IA** | Números genéricos (teléfono, CP) disparan "doc inventado"; respuestas numéricas cortas se descartan por puerta de idioma. | 🟠 |
| **OCR / preprocesado** | Calibración de clasificación scan/foto; caches (ya thread-local); paralelismo (ya hecho). | 🟡 |
| **Planos** | `_parse_number` ambiguo (`1.234 m` → 1234 m); `scale_ratio` apenas calcula; campos ORM muertos. | 🟠 |

**Lo más valioso a atacar ahora** (no hecho todavía):
1. Migrar el modelo `Invoice` para persistir base/IVA/NIF/nº pedido + añadir
   endpoints de agregación SQL (facturación mensual, por proveedor).
2. Afinar `validation.py` para no descartar respuestas numéricas válidas.
3. Arreglar `_parse_number` de planos (alinearlo con `_parse_amount`).

---

## 2. Bloque OCR / Pipeline

### Estado general
Cascada de 4 tiers (Tesseract → PaddleOCR → PP-Structure → VLM) con score de
calidad, logging/métricas y preprocesado específico por motor. La arquitectura
es correcta.

### Hallazgos

#### ✅ HECHO — Preprocesado específico por motor (`O1/O2 AGENTS.md`)
Los motores **sí** llaman al preprocesado: `tesseract.py:59`, `paddle.py:171`,
`pp_structure.py:74`. Deskew, OSD, DPI, denoise, binarización adaptativa todos
presentes en `preprocess.py`. El `AGENTS.md` estaba desactualizado.

#### ✅ HECHO — Score de calidad, no longitud (`O3`)
`cascading.py:53` `_quality()` combina confianza×0.5 + densidad×0.3 + longitud×0.2.
`_is_better` y `_try_tier3` usan `_quality` con épsilon.

#### ✅ HECHO — Caches thread-local + paralelismo de páginas
`_preprocess_cache`, `_osd_cache`, `current_language` ahora son thread-local
(`preprocess.py`, `cascading.py`). `parse_pdf` paraleliza OCR de páginas escaneadas
con `ThreadPoolExecutor` (`pdf.py`, `ocr_page_parallelism=2`).

#### ✅ HECHO — DPI threshold 0.40 → 0.55
`pdf.py:257`. Más páginas se benefician del reintentos a 400 DPI.

#### ✅ HECHO — `processing_time_ms` poblado en path PDF
Antes siempre NULL; ahora se registra y persiste.

#### ⚠️ PENDIENTE — `_looks_like_scan` sin métrica de calibración 🟡
`preprocess.py:101`. La decisión scan/foto ya tiene métrica `track_preprocess_path_chosen`
(HECHO), pero los umbrales (`extreme_ratio > 0.55`, `color_var < 70`) no están
calibrados con datos reales.
**Solución:** tras acumular métricas, ajustar umbrales; o probar ambos paths para
Tesseract y elegir por `_quality` (más robusto, +coste).

#### ⚠️ PENDIENTE — Ruido de OSD por página en PDFs grandes 🟡
Aunque el caché OSD es thread-local por página, en un PDF de 50 páginas se ejecuta
50 veces (una por página). Para documentos con la misma orientación, el OSD podría
detectarse una vez y reutilizarse.
**Solución:** opcional — cachear OSD por `(path_pdf, page_index)` a nivel documento
con TTL corto. Bajo impacto (OSD ~200ms × 50 = 10s en docs de 50 págs).

#### ⚠️ PENDIENTE — `_is_acceptable` acepta Tesseract mediocre 🟠
El 62% de páginas se resuelven con Tesseract (avg conf 0.682). El umbral
`min_confidence` decide si escalar a GPU. Si es muy bajo, muchas páginas mediocres
no escalan y la GPU queda ociosa mientras el texto es mediocre.
**Solución:** revisar `ocr_cascading_min_confidence` con la distribución de
confianza real; subirlo fuerza más escalado a Paddle (mejor texto, más coste).

---

## 3. Bloque IA / Conversacional

### Estado general
Fallback grounded siempre presente, circuit breaker en el cliente de chat,
sanitización anti-inyección, marcado de OCR dudoso. Robusto.

### Hallazgos

#### ⚠️ PENDIENTE — `validation.py:491-503` rechaza respuestas con números genéricos 🔴
El regex `_DOC_NUMBER_PATTERN` (`\d{5,8}`) captura cualquier número de 5-8 dígitos
como "número de documento". Una respuesta que cite un teléfono, código postal, o
un total "12345" se rechaza por "documento inventado".
**Solución:** exigir contexto around del número (prefijo "nº", "factura", "presupuesto")
o excluir números adyacentes a símbolos monetarios / formatos de teléfono.

#### ⚠️ PENDIENTE — `validation.py:125-127` respuestas numéricas cortas descartadas 🟠
`response_looks_spanish` requiere diacríticos o hints. Una respuesta "Total: 1234,56 €"
no tiene ni uno ni otro → `False` → se descarta. Es **el caso de uso central**
(facturas/presupuestos) y el más propenso a tropezar.
**Solución:** aceptar respuestas numéricas cortas sin pasar la puerta de idioma
(son neutras), o añadir hints numéricos (`€`, `EUR`, `total`, `importe`).

#### ⚠️ PENDIENTE — `local_client.py:162` respuesta malformada sin validar 🟠
`payload["choices"][0]["message"]["content"]` sin validar estructura. Si el backend
devuelve `choices` vacío o `message: null`, lanza `KeyError` que cae al fallback
genérico pero se loguea como "Unexpected error" en vez de "malformed response".
**Solución:** validar estructura antes de acceder; lanzar excepción tipada.

#### ⚠️ PENDIENTE — `local_client.py:184` timeout escalar en streaming 🟡
`httpx.AsyncClient(timeout=escalar)` es timeout total, no read-timeout por chunk.
Un stream que manda 1 token cada 119s nunca dispara timeout pero ocupa el semáforo.
**Solución:** `httpx.Timeout(connect=5, read=120, write=5, pool=10)`.

#### ⚠️ PENDIENTE — `LocalVisionClient` sin reintento/breaker 🟡
`local_client.py:374-484`. Inconsistente con el cliente de chat (que sí tiene).
Un 503 del vision model propaga directamente.
**Solución:** aplicar el mismo patrón de reintento/backoff que el chat.

#### ⚠️ PENDIENTE — `prompts.py:140-146` budget de tokens descarta items enteros 🟡
Si el primer item excede el budget, los demás se descartan. Sin truncado parcial.
**Solución:** permitir truncar un item individual para dejar hueco a otros.

#### ✅ VERIFICADO — `embeddings.py:37` vs `config.py:259` dimensión default (sin problema)
La auditoría inicial marcó un mismatch (comentario decía 1024, setting default 768).
**Verificado en BD:** la columna pgvector es `vector(768)` y el setting es 768 →
**coinciden**. 35.087 chunks con embedding, solo 65 pendientes. El comentario de
`embeddings.py` es engañoso (debería decir 768) pero no hay bug funcional.
**Solución:** actualizar el comentario para que diga 768 y reducir confusión.

#### ⚠️ PENDIENTE — `config.py:262` `embedding_fallback_to_hash` huérfano ⚪
Setting definido pero **nunca leído** en el código. Política no implementada.
**Solución:** implementar el fallback o eliminar el setting para no confundir.

---

## 4. Bloque Recuperación / Búsqueda

### Estado general
RRF robusto, query/passage mode correcto, chunking estructural, reranker. La
auditoría confirmó que la mayoría del pipeline está bien hecho.

### Hallazgos

#### ✅ HECHO — BM25 con `'spanish'` (antes `'simple'`)
Migración `0039`, `bm25.py:169,174`. `importes→importe` y `facturación→factura`
ahora matchean. +20-30% recall léxico.

#### ✅ HECHO — Tablas alineadas por espacios en chunking
`chunking.py` `_split_table_block` detecta bloques de líneas alineadas (≥2 líneas).
Líneas de factura escaneada se mantienen juntas.

#### ✅ HECHO — Reranker en búsqueda semántica + texto completo
`search_semantic` ahora aplica rerank + MMR. `SearchResult.full_text` para que el
cross-encoder vea el chunk completo, no el excerpt de 320 chars.

#### ⚠️ PENDIENTE — Re-embeber documentos existentes 🟠
Los chunks ya indexados conservan el troceado viejo (sin detección de tablas
alineadas). Para aprovechar el nuevo chunking, hay que re-embeber.
**Solución:** job de reembed marcando `needs_reembedding=True` en los documentos
con `low_ocr_confidence`/`page_without_text` (el setting ya existe).

#### ⚠️ PENDIENTE — `min_ocr_confidence` no-op en rama BM25 🟡
`bm25.py:386-394` declara el filtro pero es `pass`. Solo la rama semántica lo aplica.
**Solución:** aplicar el filtro vía join a `document_pages` como hace la semántica.

#### ⚠️ PENDIENTE — Chunking no cruza frontera de página 🟡
El último chunk de página N y el primero de N+1 no se solapan. Un dato que cruza
salto de página (tabla partida) se recupera peor.
**Solución:** opcional — solapar el último/primero entre páginas adyacentes.

---

## 5. Bloque Extracción de negocio / Planos

### Estado general
`_parse_amount` (business) y `dates.py` son robustos. La extracción de planos
tiene bugs de correctitud.

### Hallazgos

#### ⚠️ PENDIENTE — Factura pierde base/IVA/NIF/nº pedido al persistir 🔴
`business_extraction.py:367-377` extrae `taxable_base`, `vat_amount`,
`supplier_tax_id`, `related_order_number`, pero el modelo `Invoice`
(`professional.py:129-148`) **no tiene esas columnas** → se calculan, se validan
y se descartan. Solo `total_amount` sobrevive.
**Solución:** migración que añada columnas a `invoices`; persistir los campos en
`persist_invoice_extraction`. Impacto: conciliación fiscal posible.

#### ⚠️ PENDIENTE — Facturas no extraen líneas 🔴
`business_extraction.py:197` `extract_invoice(...)` **no recibe `pages`** (a
diferencia de budget/order). Las `InvoiceExtraction.lines` no se pueblan; la
consistencia de líneas no se valida.
**Solución:** pasar `pages` a `extract_invoice` como hacen los otros dos.

#### ⚠️ PENDIENTE — Sin agregaciones SQL sobre importes 🔴
No existe `SELECT SUM(total_amount) ... WHERE month(date)=5` en ningún sitio.
La consulta "suma de facturas de mayo" **no es resoluble en SQL**. Los importes
están como texto en `DocumentEntity.entity_value`, sin columna numérica indexada.
**Solución:** añadir endpoints de agregación en `routes/invoices.py`: suma por
mes, por proveedor, por año. Indexar `Invoice.date` y `Invoice.total_amount`.

#### ⚠️ PENDIENTE — `_parse_number` de planos ambiguo 🟠
`plan_extraction.py:540-544`. `"1.234 m"` → 1234.0 (interpreta punto como
separador de miles). En planos, `1.234 m` (1 metro 234) es válido. Inconsistente
con `_parse_amount` (business) que sí valida agrupamiento estricto.
**Solución:** alinear con `_parse_amount` o añadir heurística: si hay unidades
(m/cm/mm) próximas, tratar como decimal.

#### ⚠️ PENDIENTE — `scale_ratio` apenas calcula nada 🟠
`plan_extraction.py:747-751`. Solo valida cuando hay bbox+dpi (raro en path de
texto). `value_m` siempre viene del texto OCR, nunca de conversión píxel→metro.
**Solución:** propagar `text_blocks` con bbox desde el parser (no solo texto
plano); entonces `scale_ratio` puede derivar `value_m` real.

#### ⚠️ PENDIENTE — Campos ORM muertos en planos ⚪
`PlanRoom.polygon_json` (`business.py:150`) siempre None (`plan_extraction.py:599`).
`width_m`/`length_m` vacíos salvo formato `AxB m`. `PlanDimension.page_number`/`bbox_*`
None en path de texto puro (`plan_extraction.py:455-457`).
**Solución:** poblar donde sea posible; o eliminar columnas muertas para reducir
confusión. Baja prioridad.

#### ⚠️ PENDIENTE — `_status` fallback clasifica mal 🟡
`business_extraction.py:708-710`. Un documento sin `Estado:` puede quedar marcado
"pendiente"/"aceptado" por texto colateral ("pendiente de pago" en un footer).
**Solución:** solo clasificar status cuando hay label `Estado:` explícito.

---

## 6. Bloque Infraestructura / Observabilidad

### Estado general
Healthchecks en todos los servicios, métricas Prometheus ricas, logs estructurados,
backups scriptados. Muy sólido.

### Hallazgos

#### ⚠️ PENDIENTE — `docker-compose.yml` (dev) sin `mem_limit` 🟠
Ningún servicio (postgres, redis, workers GPU incluidos) tiene `mem_limit`/`cpus`.
Un leak de VRAM/RAM en PaddleOCR puede OOMear el host. `docker-compose.prod.yml`
sí los lleva.
**Solución:** añadir `mem_limit` a los servicios GPU (`mem_limit: 8g`) y a
postgres/redis en el compose de dev.

#### ⚠️ PENDIENTE — `worker_max_memory_bytes` ausente 🟡
`celery_app.py:31` tiene `worker_max_tasks_per_child=50` pero no
`worker_max_memory_bytes`. Para workers GPU que cargan modelos pesados, reciclar
por memoria es más fiable que por conteo.
**Solución:** añadir `worker_max_memory_bytes='4GB'` (ajustar según VRAM/RAM).

#### ⚠️ PENDIENTE — Healthcheck de backup verifica solo existencia ⚪
`admin_system.py:338` comprueba que los scripts existen, no si el último backup
es reciente o válido.
**Solución:** verificar fecha del último dump (manifest.json) y alertar si >7 días.

---

## 7. Bloque Frontend

### Estado general
**Refactorizado y correcto.** Code-splitting con `React.lazy`, rutas protegidas
por rol en el router, AdminPage dividido en sub-rutas, endpoint de conteo
dedicado para el badge. Lo que un brief inicial marcaba como pendiente **ya está
resuelto**.

### Hallazgos

#### ✅ HECHO — Code-splitting, gating por rol, errorElement, 404
`router.tsx`. Todo implementado. Sin problemas.

#### ✅ HECHO — AdminPage en sub-rutas + badge con endpoint de conteo
AdminPage (~2.8KB) es un shell con `<Outlet/>`. `useWorkInboxCount` con endpoint
dedicado `/admin/work-inbox/count`.

**Sin problemas reales en frontend.** No requiere acción.

---

## 8. Lo que ya está bien hecho (no tocar)

Para evitar regressiones, esto **no** debe cambiarse:

- **RRF híbrido** (`search_service.py:543`) — robusto, k=60 configurable.
- **Query/passage mode** (`embeddings.py`) — Granite asimétrico correcto.
- **Chunking estructural** (`chunking.py`) — respeta frases/párrafos/páginas/tablas.
- **Metadatos en embeddings** — cabecera `[tipo|fichero|pág]` + filtros.
- **`_parse_amount`** (`business_extraction.py:1072`) — maneja es-ES y en-US.
- **`dates.py`** — cubre numérico y textual español.
- **Circuit breaker del chat** (`local_client.py`) — reintenta 5xx, no 4xx.
- **Sanitización anti-inyección** (`prompts.py` R2) — XML wrap de chunks.
- **Fallback grounded** (`agent.py`) — siempre presente, atribución honesta.
- **Magic bytes en uploads** (`file_security.py`) — PDF/PNG/Office + bloqueo executables.
- **Healthchecks Docker** — todos los servicios con `condition: service_healthy`.
- **Métricas Prometheus** (`metrics/endpoint.py`) — ricas y estructuradas.
- **Backups scriptados** (`scripts/backup.ps1`) — pg_dump + retención + verificación.

---

## 9. Plan de ejecución priorizado

Ordenado por **impacto en el caso de uso real** (facturas/presupuestos/planos en
español) y factibilidad.

### Sprint 1 — Extracción de factura (alta prioridad)

| # | Tarea | Severidad | Archivo |
|---|---|---|---|
| N1 | Migración: añadir `taxable_base`, `vat_amount`, `supplier_tax_id`, `related_order_number` a `invoices` | 🔴 | `alembic/versions/`, `models/professional.py` |
| N2 | Persistir esos campos en `persist_invoice_extraction` | 🔴 | `business_extraction.py` |
| N3 | Pasar `pages` a `extract_invoice` para extraer líneas | 🔴 | `business_extraction.py:197` |
| N4 | Endpoints de agregación: suma por mes/proveedor/año + índices | 🔴 | `routes/invoices.py` |

### Sprint 2 — Calidad de respuestas IA

| # | Tarea | Severidad | Archivo |
|---|---|---|---|
| A1 | `validation.py`: no rechazar números genéricos (teléfono/CP) | 🔴 | `validation.py:491-503` |
| A2 | `validation.py`: aceptar respuestas numéricas cortas en puerta de idioma | 🟠 | `validation.py:125-127` |
| A3 | `local_client.py`: validar estructura de respuesta + timeout por chunk | 🟠 | `local_client.py:162,184` |
| A4 | Actualizar comentario engañoso en `embeddings.py:37` (dice 1024, es 768) | ⚪ | `embeddings.py` |

### Sprint 3 — Planos

| # | Tarea | Severidad | Archivo |
|---|---|---|---|
| P1 | Arreglar `_parse_number` (alinear con `_parse_amount`) | 🟠 | `plan_extraction.py:540` |
| P2 | Propagar `text_blocks` con bbox desde el parser para que `scale_ratio` calcule | 🟠 | `plan_extraction.py`, `pdf.py` |
| P3 | `_status` solo clasificar con label `Estado:` explícito | 🟡 | `business_extraction.py:708` |

### Sprint 4 — Robustez infra

| # | Tarea | Severidad | Archivo |
|---|---|---|---|
| I1 | `mem_limit` en compose de dev (workers GPU, postgres) | 🟠 | `docker-compose.yml` |
| I2 | `worker_max_memory_bytes` en Celery | 🟡 | `celery_app.py` |
| I3 | Re-embeber documentos existentes (aprovechar nuevo chunking) | 🟠 | job mantenimiento |

### Sprint 5 — Pulido (baja prioridad)

| # | Tarea | Severidad | Archivo |
|---|---|---|---|
| L1 | Eliminar `embedding_fallback_to_hash` huérfano o implementarlo | ⚪ | `config.py:262` |
| L2 | `min_ocr_confidence` efectivo en rama BM25 | 🟡 | `bm25.py:386` |
| L3 | Chunking con solapado entre páginas adyacentes | 🟡 | `chunking.py` |
| L4 | Limpiar campos ORM muertos (`polygon_json`, etc.) | ⚪ | `models/business.py` |
| L5 | Healthcheck de backup con frescura | ⚪ | `admin_system.py:338` |

---

## Métricas de éxito

Tras implementar los Sprints 1-2:

- [ ] `SELECT SUM(total_amount) FROM invoices WHERE date_trunc('month', date) = '2026-05-01'` responde "suma de facturas de mayo" sin cargar Python.
- [ ] Base/IVA/NIF/nº pedido visibles en el detail de factura y consultables por SQL.
- [ ] Una respuesta "Total: 1234,56 €" no se descarta por puerta de idioma.
- [ ] Una respuesta que cita un teléfono no se rechaza por "doc inventado".
- [ ] `1.234 m` en un plano se interpreta como 1.234 m (no 1234).
- [ ] Workers GPU con `mem_limit` no OOMean el host ante un leak.

---

## Apéndice: commits ya aplicados

| Commit | Contenido |
|---|---|
| `bdfd90b` | Migración plans, photo classification unificado, quality score (min), invoice_date fix, DPI 0.55, métricas preprocess, OSD cache |
| `68774ce` | Paralelismo OCR por página, caches thread-local, `processing_time_ms`, concurrencia GPU configurable |
| `44536ee` | BM25 español, tablas alineadas en chunking, reranker en semántica + texto completo |

Migraciones aplicadas en BD: `0038` (plans project_phase/revision), `0039` (tsv spanish).
13 documentos reencolados tras reinicio de workers.
