# Plan de Optimización — Docu-Intel

## Métricas actuales (estimadas)

| Métrica | Valor |
|---------|-------|
| Latencia total por pregunta | 4-45s |
| Generación LLM (qwen3-14b) | 8-25s + 2-10s thinking |
| Embedding (HTTP) | 50-200ms |
| Reranker GPU | 50-300ms |
| Cache hit rate | 5-15% |
| Chunks/doc | 5-40 |
| System prompt | ~1100 tokens |
| Contexto al LLM | 3-6 items, ~3000-5000 tokens |

---

## 🔴 ALTA — Velocidad

### O1. Instrumentar latencia del LLM
- **Archivo:** `app/ai/local_client.py` → `chat()`, `chat_stream()`
- **Cambio:** Añadir `time.perf_counter()` antes/después de cada llamada HTTP. Loggear duración y tokens.
- **Impacto:** Sin esto no se puede medir nada.

### O2. asyncio.run() bloqueante en query_transformer
- **Archivo:** `app/services/query_transformer.py` líneas 337, 365
- **Problema:** `asyncio.run()` dentro de un contexto async crea un event loop nuevo y bloquea el hilo.
- **Cambio:** Usar `await` directo o `asyncio.to_thread()`.
- **Ahorro:** 2-5s por pregunta (elimina bloqueo del loop).

### O3. HyDE usa el mismo LLM 14B para transformar queries
- **Archivo:** `app/services/query_transformer.py`
- **Problema:** Cada pregunta dispara una llamada LLM adicional (HyDE/multi-query) antes de la llamada principal. Con qwen3-14b esto suma 2-5s.
- **Opciones:**
  - A) Usar modelo pequeño (qwen2.5-3b o similar) solo para query transform
  - B) cachear transforms por hash de pregunta (TTL 1h)
  - C) desactivar HyDE para queries cortas (<5 palabras)
- **Ahorro:** 2-5s por pregunta.

### O4. Cache semántico recalcula embedding en cada request
- **Archivo:** `app/services/ai_cache.py`
- **Problema:** `get_cached_answer_async()` llama `embed_text(question)` para buscar respuestas similares. Esto es una llamada HTTP por cada pregunta, incluso si no hay cache hit.
- **Cambio:** cachear el embedding de query (in-process dict, TTL 5min).
- **Ahorro:** 50-200ms por pregunta.

### O5. PP-Structure reinstanciación de modelos
- **Archivo:** `app/ocr/pp_structure.py`
- **Problema:** Los logs muestran que los modelos PaddleX se cargan por cada documento (aunque están en caché de disco). El singleton `PPStructureEngine` se comparte entre llamadas pero la compilación de grafos ocurre en el primer `extract()`.
- **Cambio:** Asegurar que el singleton se reutiliza correctamente entre documentos del mismo worker. Verificar que `_model` no se resetea.
- **Ahorro:** 5-10s por documento en la primera llamada.

### O6. Constante de overhead de prompt desactualizada
- **Archivo:** `app/ai/prompts.py` línea 61
- **Problema:** `_PROMPT_OVERHEAD_TOKENS = 800` pero el system prompt real es ~1100 tokens. Esto permite 1 item extra de contexto que el modelo no puede procesar.
- **Cambio:** Actualizar a 1100.
- **Impacto:** Evita truncado silencioso.

---

## 🟠 MEDIA — Calidad

### O7. adaptive_weights() es dead code
- **Archivo:** `app/services/bm25.py` y `search_service.py`
- **Problema:** La función `adaptive_weights()` pondera BM25/cosine/text según tipo de query, pero nunca se llama desde `search_hybrid`. La fusión RRF trata todas las estrategias por igual.
- **Opciones:**
  - A) Conectar `adaptive_weights()` a la fusión RRF (multiplicar contribución por peso)
  - B) Eliminar el código muerto
- **Impacto:** Mejor ranking para queries numéricas vs naturales.

### O8. _FOLLOWUP_HINTS demasiado amplio
- **Archivo:** `app/ai/validation.py` línea 553
- **Problema:** `" y "` (solo "and") activa memoria para ~30-40% de preguntas que no son follow-ups.
- **Cambio:** Exigir que la pregunta anterior contenga entidades detectadas, o que la pregunta actual sea corta (<40 chars) además de contener "y".

### O9. Memory + reference_resolver duplican trabajo
- **Archivos:** `app/ai/validation.py` (`build_memory_block`) + `app/ai/reference_resolver.py`
- **Problema:** Para "este presupuesto", el reference resolver reescribe la pregunta Y el memory block inyecta contexto previo. Resultado: misma entidad duplicada.
- **Cambio:** Cuando `resolve_references()` resuelve algo, desactivar `build_memory_block()`.

### O10. System prompt comprimible
- **Archivo:** `app/ai/prompts.py` → `_SYSTEM_PROMPT`
- **Cambios:**
  - Catálogo de tipos: 9 categorías con ejemplos → 3 líneas resumen
  - Explicación de contexto: redundante con el formato real
  - Reglas de estilo: consolidar 8 bullets en 4
  - Caso edge commercial: eliminar (raro)
- **Ahorro:** ~500 tokens = 1-2 items extra de contexto.

### O11. Streaming reconstruye pipeline completo
- **Archivo:** `app/api/routes/ai.py` (`ask_stream`)
- **Problema:** El endpoint streaming reimplementa toda la lógica de `answer_question()` (reference resolution, tool selection, context collection, gates). Puede driftar.
- **Cambio:** Refactorizar para reusar `answer_question()` con un callback de streaming, o al menos extraer la lógica pre-LLM a una función compartida.

### O12. Intent se clasifica dos veces
- **Archivos:** `app/ai/agent.py` línea 267 + `app/ai/tools.py` línea 768
- **Problema:** `classify_intent()` se ejecuta en el orchestrator Y en `select_structured_tools()`.
- **Cambio:** Pasar el resultado de la primera clasificación al segundo.

### O13. Chunker no separa páginas
- **Archivo:** `app/services/chunking.py`
- **Problema:** Un párrafo que cruza un salto de página termina en un solo chunk. Los datos de página se pierden.
- **Cambio:** Añadir separación por `page_number` antes de agrupar texto.

### O14. Cache search se invalida globalmente
- **Archivo:** `app/services/cache.py` → `invalidate_search_cache()`
- **Problema:** Cualquier cambio de documento borra TODAS las búsquedas cacheadas (patrón `search:*`).
- **Cambio:** Claves por hash de query+filters, invalidación por documento específico o TTL más corto.

---

## 🟡 BAJA — Incrementales

| # | Problema | Solución |
|---|----------|----------|
| O15 | Circuit breaker sin métricas Prometheus | Añadir counters de trip/recovery |
| O16 | Latencia embedding sync subestimada (mide cache-write, no el batch real) | Mover timer para envolver `_generate_embeddings_batch` |
| O17 | Documentos con OCR bajo confianza se indexan igual | Filtrar chunks con confidence < 0.3 del embedding |
| O18 | Reranker carga modelo en CPU si no hay GPU | Ya auto-detecta CUDA; verificar que funciona en CPU |
| O19 | Plan extraction: escala extraída pero no usada para cálculos | Implementar conversión px→m usando DPI + scale_ratio |
| O20 | vision_on_demand descarga modelo cada 300s | Reducir a 120s en batch ingestion, 600s en uso normal |

---

## Orden de ejecución recomendado

| Fase | Tareas | Ahorro estimado |
|------|--------|-----------------|
| **F1** (1h) | O1 (instrumentación) + O6 (constante) + O12 (dedup intent) | Habilita medición |
| **F2** (2h) | O2 (asyncio fix) + O4 (cache embedding) | 2-7s/pregunta |
| **F3** (3h) | O3 (query transform ligero) + O10 (prompt comprimido) | 2-5s/pregunta + mejor contexto |
| **F4** (2h) | O8 (followup hints) + O9 (dedup memoria) | Menos ruido en contexto |
| **F5** (4h) | O7 (adaptive weights) + O13 (chunker páginas) | Mejor retrieval |
| **F6** (3h) | O11 (unificar streaming) + O14 (cache selectiva) | Mantenibilidad |
| **F7** (2h) | O15-O20 (incrementales) | Robustez |

---

## Verificación

- [ ] Latencia por pregunta medida y loggeada (O1)
- [ ] asyncio.run() eliminado del query transformer (O2)
- [ ] Cache embedding de query activo (O4)
- [ ] System prompt < 700 tokens (O10)
- [ ] Follow-ups no se activan para queries standalone (O8)
- [ ] Adaptive weights conectado o eliminado (O7)
- [ ] Chunker respeta límites de página (O13)
- [ ] Tests existentes en verde tras cada cambio
