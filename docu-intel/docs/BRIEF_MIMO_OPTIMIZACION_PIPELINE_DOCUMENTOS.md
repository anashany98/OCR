# Brief para Mimo: optimización end-to-end del pipeline documental

> Documento de ejecución para Mimo. Objetivo: reducir tiempo desde entrada del documento hasta disponibilidad para consulta, aumentar throughput y evitar repetir trabajo caro. Mantener precisión OCR, calidad RAG y contratos públicos existentes.

## 0. Contexto

- Backend: FastAPI, Celery, PostgreSQL/pgvector y Redis.
- OCR: Tesseract, PaddleOCR, PP-Structure y fallback VLM opcional.
- Procesamiento actual: registro → parseo/rasterizado → OCR → persistencia → clasificación/extracción → chunking → embeddings → documento procesado.
- Workers actuales: `text_fast`, `ocr_heavy`, `embeddings` y `maintenance`.
- Hardware: 2× RTX 4070; OCR y embeddings deben usar GPUs separadas.

## 1. Problema principal

El procesamiento completo sigue siendo monolítico por documento. El worker OCR también ejecuta clasificación, extracción, chunking y embeddings antes de liberar la tarea y marcar el documento como consultable.

Consecuencias:

- GPU OCR puede quedar esperando al proveedor de embeddings.
- GPU dedicada a embeddings no se aprovecha durante la ingesta inicial.
- Un fallo tardío puede repetir OCR ya completado.
- Documentos grandes no ofrecen resultados parciales.
- PDFs digitales reservan cola GPU antes de saber que no necesitan OCR.
- Renderizado de previews retrasa disponibilidad para búsqueda.
- Picos de RAM y transacciones grandes al preparar todos los chunks juntos.

## 2. Objetivo arquitectónico

Separar pipeline en etapas idempotentes y observables:

```text
registro
  ↓
sondeo CPU del documento
  ├─ digital → extracción CPU
  ├─ mixto   → texto CPU + OCR solo de páginas escaneadas
  └─ scan    → OCR GPU
                 ↓
        persistencia incremental
                 ↓
    clasificación y extracción
                 ↓
       chunking incremental
                 ↓
    búsqueda léxica disponible
                 ↓
      embeddings en GPU 2
                 ↓
    búsqueda híbrida disponible
```

Estados recomendados:

- `registered`
- `probing`
- `text_processing`
- `text_ready`
- `metadata_ready`
- `embedding_pending`
- `searchable`
- `fully_processed`
- `needs_review`
- `failed`

No es obligatorio sustituir inmediatamente `Document.status`. Se pueden introducir campos de progreso por etapa y mantener estados públicos compatibles durante migración.

## 3. Reglas obligatorias

1. No romper `BaseOCREngine.extract(image_path: Path) -> OCRResult`.
2. No romper firmas públicas de `embed_many`, `embed_query_text` ni `search_*`.
3. Mantener política sin hash fallback silencioso.
4. Cada tarea debe ser idempotente y segura ante entrega duplicada de Celery.
5. No ejecutar OCR de nuevo cuando solo cambie modelo de embeddings.
6. No ejecutar embeddings de nuevo cuando entrada y versión del modelo no cambien.
7. Añadir migración Alembic para cualquier cambio de esquema.
8. Añadir tests por cambio de comportamiento.
9. Mantener búsqueda léxica disponible aunque proveedor de embeddings falle.
10. Un commit revisable por tarea: `P0.1`, `P0.2`, etc.

---

# FASE P0 — Medir y desacoplar

## P0.1 · Métricas de tiempo por etapa

### Archivos candidatos

- `backend/app/services/document_processing_core.py`
- `backend/app/services/document_embedding_pipeline.py`
- `backend/app/parsers/pdf.py`
- `backend/app/services/metrics/`
- `backend/app/workers/tasks.py`

### Cambio requerido

Medir histogramas y contadores para:

- `document_queue_wait_seconds`
- `document_probe_seconds`
- `document_render_seconds`
- `document_ocr_seconds`
- `document_persist_seconds`
- `document_classification_seconds`
- `document_extraction_seconds`
- `document_chunking_seconds`
- `document_embedding_seconds`
- `document_total_to_text_ready_seconds`
- `document_total_to_searchable_seconds`
- `document_stage_failures_total{stage,reason}`
- `document_pages_processed_total{route,engine}`

Guardar también timestamps de etapa en base de datos o tabla de eventos existente para análisis por documento.

### Aceptación

- Panel o endpoint permite obtener P50/P95 por tipo documental.
- Se distingue espera en cola de tiempo efectivo de ejecución.
- Métricas no incluyen filename/document_id como label Prometheus.

## P0.2 · Separar embeddings del worker OCR

### Archivos candidatos

- `backend/app/services/document_processing_core.py`
- `backend/app/services/document_embedding_pipeline.py`
- `backend/app/workers/embedding_tasks.py`
- `backend/app/workers/celery_app.py`
- `backend/app/workers/routing.py`

### Problema verificado

`_process_full_parse()` llama a `_replace_document_chunks()` y esta función genera embeddings sincrónicamente. Cola `embeddings` existe, pero ingesta inicial no la aprovecha.

### Cambio requerido

1. Separar construcción/persistencia de chunks de creación de vectores.
2. Durante procesamiento OCR:
   - Persistir chunks con `embedding=NULL`.
   - Marcar `needs_reembedding=True` y etapa `embedding_pending`.
   - Hacer commit de texto, bloques, extracción y chunks.
3. Encolar tarea dedicada en cola `embeddings` después del commit.
4. Tarea de embeddings:
   - Cargar chunks pendientes.
   - Generar vectores por microbatches.
   - Actualizar versión/proveedor por lote.
   - Marcar documento `searchable` al completar.
5. Si embeddings fallan, mantener documento consultable mediante búsqueda léxica.

### Precauciones

- Encolar solo después del commit para evitar que worker lea filas todavía invisibles.
- Usar identificador idempotente por documento y versión de embedding.
- Evitar que dos tareas embeban simultáneamente mismos chunks.
- No usar hash embedding como fallback.

### Aceptación

- Worker `ocr_heavy` no llama a proveedor de embeddings.
- Worker `embeddings` procesa ingesta inicial.
- Fallo del proveedor no cambia texto ya persistido ni obliga a repetir OCR.
- Documento aparece en búsqueda léxica antes de disponer de vector.

## P0.3 · Estado consultable por etapas

### Cambio requerido

Introducir señal explícita que diferencie:

- Texto listo para búsqueda léxica.
- Embeddings pendientes.
- Búsqueda híbrida lista.
- Procesamiento complementario terminado.

Exponer progreso en API sin romper consumidores actuales.

Ejemplo de payload:

```json
{
  "status": "processing",
  "pipeline_stage": "embedding_pending",
  "text_search_ready": true,
  "semantic_search_ready": false,
  "pages_completed": 20,
  "pages_total": 20
}
```

### Aceptación

- UI puede permitir consulta léxica mientras embeddings están pendientes.
- Reintento de embeddings no devuelve documento a estado OCR.

---

# FASE P1 — Enrutado barato e ingesta rápida

## P1.1 · Sondeo CPU antes de seleccionar cola pesada

### Archivos candidatos

- `backend/app/services/document_registration_service.py`
- `backend/app/workers/routing.py`
- `backend/app/parsers/content_router.py`
- Nuevo `backend/app/services/document_probe.py`

### Cambio requerido

Crear sondeo barato para PDF:

- Número de páginas.
- Tamaño físico y dimensiones.
- Texto incrustado en muestra de primeras páginas.
- Proporción estimada digital/escaneada.
- Señales de plano/documento especial.
- Lista inicial de páginas probablemente escaneadas.

Rutas:

- Digital → `text_fast`.
- Escaneado → `ocr_heavy`.
- Mixto → extracción digital CPU y OCR solo para páginas necesarias.
- Plano → ruta pesada específica si existe.

### Aceptación

- PDF digital no reserva worker GPU.
- PDF mixto no pasa todas sus páginas por OCR.
- Sondeo tiene timeout y fallback seguro a `ocr_heavy`.

## P1.2 · Diferir previews no críticas

### Archivos candidatos

- `backend/app/parsers/pdf.py`
- Nuevo `backend/app/workers/preview_tasks.py`

### Cambio requerido

Para PDF digital:

- Extraer texto primero.
- Generar miniatura de primera página durante ruta principal si UI la necesita.
- Generar resto de previews en cola de baja prioridad o bajo demanda.
- No bloquear estado `text_ready` por previews.

Para páginas escaneadas, reutilizar render OCR como preview; no renderizar dos veces.

### Aceptación

- PDF digital de muchas páginas queda consultable sin esperar previews completas.
- Apertura posterior de página sin preview dispara generación segura.

## P1.3 · Backpressure por cola y recurso

### Cambio requerido

Aplicar límites separados:

- Pendientes OCR.
- Pendientes embeddings.
- Documentos grandes.
- Páginas totales en vuelo.
- Uso de VRAM/memoria cuando métrica esté disponible.

Priorizar documentos pequeños sin provocar starvation de grandes. Usar clases de prioridad o round-robin, no solo FIFO global.

### Aceptación

- Lote de documentos grandes no impide procesar indefinidamente documentos pequeños.
- Saturación de embeddings no detiene OCR ni ingesta léxica.

---

# FASE P2 — Procesamiento incremental e idempotente

## P2.1 · Checkpoints por lote de páginas

### Cambio requerido

Procesar documentos grandes en lotes configurables, por ejemplo 8–20 páginas:

1. Procesar lote.
2. Persistir páginas y bloques mediante bulk insert/upsert.
3. Actualizar `pages_completed`.
4. Confirmar transacción.
5. Continuar siguiente lote.

Al reintentar, continuar desde primer lote incompleto.

### Aceptación

- Fallo en página 450 no repite páginas 1–449.
- Entrega duplicada no crea páginas, bloques o chunks duplicados.
- Progreso queda visible después de cada lote confirmado.

## P2.2 · Hashes y versiones por etapa

### Campos recomendados

- `source_hash`
- `page_image_hash`
- `ocr_input_hash`
- `ocr_engine_version`
- `normalized_text_hash`
- `chunk_input_hash`
- `chunking_version`
- `embedding_input_hash`
- `embedding_model_version`

### Reglas

- Reutilizar OCR si imagen y configuración OCR no cambian.
- Reutilizar chunks si texto normalizado y configuración de chunking no cambian.
- Reutilizar embedding si texto de embedding, modelo e instrucciones no cambian.
- Cambio de modelo solo encola reembedding.

### Aceptación

- Reprocesado parcial ejecuta únicamente etapas invalidadas.
- Logs indican motivo exacto de cache hit/miss por etapa.

## P2.3 · Persistencia masiva

### Cambio requerido

Reducir `flush()` por bloque:

- Insertar páginas por lote.
- Recuperar mapa `page_number → page_id`.
- Insertar bloques por lote.
- Insertar chunks por lote.
- Mantener constraints únicos que garanticen idempotencia.

### Aceptación

- Menos round trips SQL por documento.
- Tests prueban rollback/reintento sin duplicados.
- Benchmark compara tiempo DB antes/después para 100, 500 y 1.000 páginas.

---

# FASE P3 — Embeddings eficientes

## P3.1 · Microbatching por tokens

### Cambio requerido

No enviar todos los chunks de un documento como unidad única. Construir batches por:

- Máximo de chunks.
- Máximo estimado de tokens.
- Timeout corto para agrupar trabajos.

Valores iniciales a medir:

- 32–64 chunks.
- 8.000–16.000 tokens por lote.
- Reintento por lote, no por documento completo.

### Aceptación

- Pico de RAM acotado en documentos grandes.
- Fallo de un batch no invalida vectores confirmados de batches anteriores.
- GPU de embeddings mantiene utilización estable bajo carga.

## P3.2 · Embeddings entre documentos

### Cambio requerido

Permitir que ejecutor de embeddings combine chunks pendientes de varios documentos, conservando asociación `chunk_id → vector`.

Usar lock/adquisición segura, por ejemplo `FOR UPDATE SKIP LOCKED`, para que múltiples workers no reclamen mismas filas.

### Aceptación

- Documentos pequeños no esperan a que uno enorme termine todos sus chunks.
- Dos workers no duplican cálculo.

## P3.3 · Índices y escritura de vectores

### Cambio requerido

- Verificar `EXPLAIN (ANALYZE, BUFFERS)` en búsqueda semántica e híbrida.
- Confirmar uso HNSW y GIN.
- Medir coste de actualización del índice durante ingesta masiva.
- Si carga masiva lo justifica, documentar estrategia de backfill/reindex; no desactivar índices en operación normal sin control explícito.

### Aceptación

- P95 de búsqueda no empeora con corpus objetivo.
- Consulta semántica usa índice HNSW en condiciones normales.

---

# FASE P4 — OCR adaptativo

## P4.1 · Escalera DPI basada en señales

### Cambio requerido

Antes de re-renderizar a mayor DPI, calcular señales baratas:

- Resolución efectiva.
- Contraste.
- Blur.
- Densidad de componentes/texto.
- Calidad del resultado OCR anterior.
- Ganancia marginal entre tiers.

Detener escalada cuando coste adicional no produzca mejora suficiente de calidad.

### Aceptación

- Páginas limpias no se procesan a 600 DPI.
- Páginas difíciles conservan o mejoran precisión del pipeline actual.
- Métrica registra coste y ganancia por escalada.

## P4.2 · Batching GPU de páginas

### Cambio requerido

Evaluar reemplazo gradual de paralelismo por hilos por ejecutor GPU dedicado:

- Modelo único cargado por GPU.
- Cola interna de imágenes.
- Microbatch dinámico.
- Límite de VRAM.
- Resultado correlacionado por documento/página.

Primero crear benchmark. No sustituir implementación actual si batch no mejora throughput real o perjudica estabilidad.

### Aceptación

- Comparativa páginas/minuto y P95 con 1, 2, 4 y 8 páginas concurrentes.
- Sin crecimiento sostenido de VRAM/hilos tras 100 documentos.

---

# FASE P5 — Consulta progresiva

## P5.1 · Léxica antes que semántica

### Cambio requerido

Cuando texto/chunks estén persistidos:

- Habilitar búsqueda FTS/BM25 inmediatamente.
- Excluir solo rama semántica para chunks sin vector.
- Añadir indicador de resultado parcial si documento sigue embebiéndose.

### Aceptación

- Proveedor de embeddings caído no impide consultar texto nuevo.
- Al completar embeddings, mismo documento entra automáticamente en resultados híbridos.

## P5.2 · Invalidación de caché por etapa

### Cambio requerido

Evitar invalidar toda caché global por cada documento si es posible. Introducir versión de índice/corpus o invalidación segmentada por tenant/ámbito y etapa.

### Aceptación

- Ingesta masiva no destruye continuamente tasa de aciertos de caché no relacionada.
- Resultados nuevos aparecen sin servir datos obsoletos.

---

# Estrategia de pruebas

## Unitarias

- Enrutado digital, mixto y escaneado.
- Transiciones válidas de etapa.
- Idempotencia de tareas.
- Hash/versionado por etapa.
- Formación de microbatches por tokens.
- Recuperación desde checkpoint.
- Embedding fallido mantiene búsqueda léxica.

## Integración

- PDF digital de 20 páginas.
- PDF escaneado de 20 páginas.
- PDF mixto de 20 páginas.
- Documento de 500 páginas con fallo inducido a mitad.
- Caída de proveedor de embeddings.
- Reinicio de worker durante OCR y durante embeddings.
- Entrega duplicada de tarea Celery.

## Rendimiento

Medir por clase documental:

- Tiempo de subida/registro.
- Tiempo en cola.
- Tiempo hasta `text_ready`.
- Tiempo hasta `searchable`.
- Páginas OCR/minuto por GPU.
- Chunks embebidos/segundo.
- P50/P95/P99.
- RAM máxima por worker.
- VRAM máxima por GPU.
- Round trips y tiempo PostgreSQL.

No usar como benchmark principal PDFs sintéticos inválidos o medir solo tiempo de upload. Usar fixtures representativos del corpus real, anonimizados.

# SLO iniciales propuestos

- PDF digital de 20 páginas: búsqueda léxica disponible en menos de 3 segundos en entorno objetivo.
- PDF escaneado: primera página persistida/visible en menos de 10 segundos, sujeto al motor y hardware.
- Embeddings empiezan antes de terminar documentos OCR extensos cuando hay chunks confirmados.
- Fallo de embeddings nunca repite OCR.
- Reintento de página/lote no duplica filas.
- Worker OCR no espera llamadas del proveedor de embeddings.
- GPU OCR dedicada a OCR; GPU 2 dedicada a embeddings.

# Orden de ejecución

| Orden | Tarea | Impacto |
|---:|---|---|
| 1 | P0.1 Métricas por etapa | Línea base y control |
| 2 | P0.2 Separar embeddings | Mayor mejora de throughput |
| 3 | P0.3 Consulta por etapas | Menor tiempo percibido |
| 4 | P1.1 Sondeo CPU | Libera GPU para scans reales |
| 5 | P1.2 Previews diferidos | Mejora PDFs digitales |
| 6 | P3.1/P3.2 Microbatch embeddings | Aprovecha GPU 2 |
| 7 | P2.1/P2.2 Checkpoints e hashes | Reintentos baratos |
| 8 | P2.3 Bulk persistence | Menor coste PostgreSQL |
| 9 | P4.1 OCR adaptativo | Menor coste por página |
| 10 | P4.2 Batching GPU | Throughput máximo tras benchmark |

# Checklist global

- [ ] Worker OCR no genera embeddings en ingesta inicial.
- [ ] Documento puede buscarse léxicamente antes de tener vector.
- [ ] PDF digital se procesa en cola CPU.
- [ ] PDF mixto solo manda páginas escaneadas a OCR.
- [ ] Previews no bloquean disponibilidad de texto.
- [ ] Hay métricas de cola y ejecución por etapa.
- [ ] Tareas son idempotentes ante duplicados.
- [ ] Reintento continúa desde checkpoint confirmado.
- [ ] Embeddings usan microbatches limitados por tokens.
- [ ] No existe hash fallback silencioso.
- [ ] HNSW/GIN se verifican mediante planes SQL.
- [ ] Benchmarks incluyen documentos reales representativos.
- [ ] Tests existentes y nuevos quedan verdes.

# Entrega esperada de Mimo por tarea

Para cada tarea:

1. Breve diagnóstico confirmado contra código actual.
2. Lista exacta de archivos modificados.
3. Migración, si corresponde.
4. Tests nuevos y existentes ejecutados.
5. Resultado de benchmark antes/después.
6. Riesgos y rollback.
7. Commit independiente con prefijo de tarea.

No mezclar optimización del frontend ni cambios funcionales de OCR/RAG no necesarios para este objetivo.
