# Plan integral de optimización de velocidad del chat RAG e IA

Fecha de creación: 2026-07-13
Proyecto: Docu-Intel
Rama de referencia: fix/remediacion-auditoria-2026-07
Objetivo: reducir radicalmente el tiempo de respuesta del chat sin degradar recuperación, citas, aislamiento de permisos ni calidad factual.

## 1. Contrato obligatorio de ejecución

Este documento es la fuente de verdad para implementar la optimización.

Reglas obligatorias:

1. Ejecutar las fases en orden, desde FASE 0 hasta FASE 8.
2. No declarar una fase terminada únicamente porque compile.
3. Conservar todos los cambios locales existentes y no modificar archivos ajenos al alcance.
4. No utilizar git reset --hard, git checkout -- ni operaciones destructivas.
5. Crear commits pequeños por tarea después de verificarla.
6. Medir siempre el camino frío y el camino caliente.
7. Ninguna mejora de velocidad puede reducir el aislamiento por usuario, grupo, hotel, proyecto o presupuesto.
8. Ninguna respuesta factual puede perder sus citas documentales.
9. No ocultar fallos mediante caché: una respuesta incorrecta rápida sigue siendo incorrecta.
10. Si una optimización empeora el quality gate, revertir únicamente esa optimización mediante su feature flag.
11. Las pruebas de permisos negativas son obligatorias.
12. No cambiar el modelo principal hasta haber corregido y medido la recuperación.

## 2. Diagnóstico medido

### 2.1 Estado actual

Modelos cargados simultáneamente en LM Studio:

- qwen3-8b: 5,03 GB, contexto 8.192, paralelismo 4.
- qwen/qwen3-14b: 9,00 GB, contexto 16.384, paralelismo 4.
- Modelo de embeddings Nomic Q4: 84 MB.

Hardware:

- Dos GPU NVIDIA GeForce RTX 4070 de 12 GB.
- El backend FastAPI no dispone de CUDA.
- El reranker local BAAI/bge-reranker-v2-m3 cae a CPU.

Evidencia de logs:

- app.services.reranker informa CUDA not available for reranker, using CPU.
- El reranker descarga o carga un CrossEncoder de aproximadamente 568 M parámetros.

### 2.2 Latencia completa observada

| Escenario | Primer evento | Primer delta | Total frío | Caché caliente |
|---|---:|---:|---:|---:|
| Aitor y condición de pago | 34,9 s | 35,9 s | 38,9 s | 5-49 ms |
| Identificador 3987_001 | 27,6 s | 28,7 s | 31,1 s | 5-55 ms |
| Archivo ppto firmado.jpeg | 22,8 s | 25,2 s | 27,6 s | 6-50 ms |

### 2.3 Tiempo aislado de recuperación

| Pregunta | Recuperación actual |
|---|---:|
| Síntesis Aitor | 57,557 s |
| Importe 3987_001 | 28,021 s |
| Archivo ppto firmado.jpeg | 24,252 s |

La recuperación simplificada, con una sola consulta y sin reranker CPU, tardó:

| Pregunta | Recuperación experimental |
|---|---:|
| Síntesis Aitor | 0,092 s |
| Importe 3987_001 | 0,093 s |
| Archivo ppto firmado.jpeg | 0,067 s |

Esta medición experimental demuestra el potencial de latencia, pero no certifica todavía la calidad.

### 2.4 Tiempo aislado del modelo

Con el mismo prompt factual corto:

| Modelo | Primera ejecución | Ejecución caliente |
|---|---:|---:|
| qwen3-8b | 5,686 s | 0,479 s |
| qwen/qwen3-14b | 0,869 s | 0,686 s |

Conclusión: el cuello principal es recuperación y reranking, no la generación corta del 14B.

### 2.5 Causa técnica

La ruta actual multiplica trabajo:

1. app.ai.context genera la pregunta original y hasta tres variantes.
2. Cada variante llama a search_hybrid.
3. search_semantic vuelve a generar hasta tres reformulaciones internas.
4. Cada reformulación genera un embedding y consulta pgvector.
5. search_semantic aplica el CrossEncoder.
6. search_hybrid puede aplicar otra vez el CrossEncoder.
7. El CrossEncoder se ejecuta en CPU dentro del backend.
8. Incluso después de resolver un nombre o identificador exacto se ejecuta hybrid_search.
9. El primer evento SSE se emite después de construir todo el contexto.

## 3. Objetivos y SLO

### 3.1 Latencia objetivo

| Tipo de pregunta | p50 objetivo | p95 objetivo |
|---|---:|---:|
| Primer evento SSE | 100 ms | 250 ms |
| Caché exacta o semántica | 100 ms | 250 ms |
| Dato estructurado exacto | 500 ms | 1 s |
| Documento por nombre o ID | 1,5 s | 3 s |
| Pregunta documental sencilla | 3 s | 6 s |
| Síntesis de varios documentos | 7 s | 12 s |

### 3.2 Calidad objetivo

- Citation recall: al menos 0,90.
- Citation precision: al menos 0,95.
- Respuestas con hechos obligatorios: al menos 0,90.
- Abstención correcta sin evidencia: 1,00.
- Cero fuentes fuera del alcance del usuario.
- Cero regresiones en exact identifier, filename query y short followup.
- Ningún documento permitido puede convertirse en fuente para un usuario sin permisos.

## 4. Arquitectura objetivo

Flujo objetivo:

1. Autenticación y resolución de permisos.
2. Emisión inmediata de event status con estado cache.
3. Caché aislada exacta y semántica.
4. Clasificación barata de intención.
5. Ruta exacta para nombre, ID, factura, pedido, albarán o presupuesto.
6. Respuesta determinista si existe un dato estructurado fiable.
7. Una única búsqueda híbrida si todavía falta contexto.
8. Reranking opcional y único sobre un conjunto pequeño.
9. Selección de modelo y presupuesto de tokens.
10. Generación y validación.
11. Persistencia, citas y caché.

## 5. FASE 0 — Baseline reproducible y controles

### Tareas

1. Congelar el conjunto golden actual.
2. Añadir una copia portable que resuelva documentos por nombre y no por IDs rígidos.
3. Medir por separado:
   - cache_lookup_ms
   - exact_lookup_ms
   - query_expansion_ms
   - lexical_ms
   - semantic_embedding_ms
   - pgvector_ms
   - bm25_ms
   - reranker_ms
   - context_build_ms
   - model_queue_ms
   - model_ttft_ms
   - generation_ms
   - persistence_ms
4. Guardar cold y warm en archivos JSON versionados.
5. Registrar número de variantes, embeddings, candidatos rerankeados y tokens de contexto.
6. Añadir flags de rollback antes de cambiar comportamiento.

### Archivos

- scripts/benchmark_ai_pipeline.py
- backend/app/services/metrics/rag.py
- backend/app/services/metrics/search.py
- backend/app/services/search_service.py
- backend/app/ai/context.py

### Pruebas

- El benchmark debe devolver código distinto de cero si falta un escenario.
- Debe distinguir first_event, first_delta y total.
- Debe registrar cache_hit.
- Debe limpiar o versionar la caché para las mediciones frías.

### Criterio de aceptación

Existe un baseline repetible para los diez escenarios y cada etapa tiene duración propia.

## 6. FASE 1 — Eliminar la expansión multiplicativa

### Problema

Hay dos capas independientes de multi-query. Su combinación puede producir muchas búsquedas, embeddings y rerankings para una sola pregunta.

### Tareas

1. Crear un único QueryPlan por pregunta.
2. El QueryPlan debe contener:
   - intent
   - original_query
   - exact_identifiers
   - filename_candidates
   - semantic_variants
   - requires_semantic
   - requires_rerank
   - answer_profile
3. Desactivar la expansión interna de search_semantic cuando el llamador ya entrega variantes.
4. Limitar semantic_variants:
   - exact identifier: cero
   - filename: cero
   - dato factual: máximo una
   - síntesis compleja: máximo dos
5. Evitar ejecutar HyDE y multi-query simultáneamente.
6. Incluir la estrategia y versión del QueryPlan en la clave de caché de búsqueda.

### Archivos

- backend/app/ai/multi_query.py
- backend/app/ai/context.py
- backend/app/services/search_service.py
- backend/app/core/config.py

### Configuración nueva

- SEARCH_QUERY_PLAN_VERSION
- SEARCH_MAX_VARIANTS_FACTUAL=1
- SEARCH_MAX_VARIANTS_SYNTHESIS=2
- SEARCH_ALLOW_NESTED_EXPANSION=false

### Pruebas

- Una pregunta exacta genera una sola consulta.
- Una pregunta factual genera como máximo dos consultas totales.
- Una síntesis genera como máximo tres consultas totales.
- El contador de embeddings coincide con el número previsto.
- Dos variantes iguales se deduplican.

### Criterio de aceptación

Ningún escenario ejecuta expansión anidada y context_build p95 queda por debajo de 2 s sin reranker.

## 7. FASE 2 — Política de reranking rápida y explícita

### Problema

BAAI/bge-reranker-v2-m3 se ejecuta en CPU dentro del backend y puede aplicarse dos veces.

### Tareas

1. Añadir SEARCH_RERANKER_ENABLED.
2. Añadir SEARCH_RERANKER_BACKEND con valores off, http o local.
3. Prohibir local+cpu en producción salvo autorización explícita.
4. Aplicar reranking una sola vez, después de fusionar resultados.
5. Limitar el pool a cinco u ocho candidatos.
6. Añadir timeout duro de 500 ms para servicio GPU y fallback inmediato.
7. Evaluar qwen3-reranker-0.6b, ya disponible localmente.
8. Comparar tres perfiles:
   - sin reranker
   - reranker 0.6B GPU
   - BGE CPU actual
9. Elegir el perfil que cumpla calidad y latencia.
10. Precargar el reranker elegido al iniciar su servicio.

### Archivos

- backend/app/services/reranker.py
- backend/app/services/search_service.py
- backend/app/services/healthchecks.py
- backend/app/core/config.py
- docker-compose.yml

### Pruebas

- El reranker nunca se ejecuta dos veces.
- off no realiza HTTP ni carga modelos.
- timeout conserva el ranking anterior.
- Un fallo no bloquea la respuesta.
- El backend no descarga modelos durante una petición.

### Criterio de aceptación

reranker_ms p95 menor de 500 ms o reranker desactivado, con citation recall mínimo 0,90.

## 8. FASE 3 — Exact-first y eliminación de búsquedas innecesarias

### Tareas

1. Detectar antes de hybrid_search:
   - nombre completo o parcial de archivo
   - document_id
   - número de factura
   - número de pedido
   - número de albarán
   - número de presupuesto
   - referencias alfanuméricas
2. Si la resolución exacta produce un documento autorizado y contexto suficiente, no ejecutar hybrid_search.
3. Si hay varios candidatos exactos, limitar la búsqueda al conjunto resuelto.
4. Normalizar guiones, barras, espacios, acentos y ceros iniciales.
5. Mantener la búsqueda semántica como fallback, no como paso obligatorio.
6. Registrar exact_resolution_hit y exact_resolution_fallback.

### Archivos

- backend/app/ai/tools.py
- backend/app/ai/context.py
- backend/app/ai/reference_resolver.py
- backend/app/services/search_service.py

### Pruebas

- 3987_001 no llama a búsqueda semántica cuando el documento existe.
- ppto firmado.jpeg no llama a hybrid_search tras resolver el archivo.
- Un identificador inexistente sí cae a búsqueda.
- Un usuario sin acceso recibe cero contexto aunque conozca el nombre exacto.
- No se filtra la existencia de un documento mediante tiempos o mensajes diferentes.

### Criterio de aceptación

Las consultas exactas terminan la recuperación en menos de 300 ms p95.

## 9. FASE 4 — Respuestas deterministas para datos estructurados

### Tareas

1. Crear un StructuredAnswerDecision.
2. Permitir respuesta sin LLM para:
   - importe total
   - moneda
   - fecha
   - número de documento
   - proveedor o cliente
   - estado
   - recuentos
3. Exigir:
   - documento autorizado
   - campo no nulo
   - confianza suficiente
   - cita documental válida
4. Generar respuesta natural mediante plantillas españolas.
5. Incluir document_id, filename, page_number y block_id cuando existan.
6. Caer al LLM si hay contradicción, baja confianza o síntesis.
7. No almacenar como determinista una respuesta con advertencia OCR sin mostrarla.

### Archivos

- backend/app/ai/context.py
- backend/app/ai/agent.py
- backend/app/api/routes/ai.py
- backend/app/ai/validation.py

### Pruebas

- Importe exacto correcto con cita.
- Fecha exacta correcta con cita.
- Dato ausente produce abstención.
- Datos de precios se ocultan a usuarios sin can_view_prices.
- OCR dudoso añade advertencia.
- Contradicciones obligan a la ruta LLM.

### Criterio de aceptación

Dato estructurado exacto p95 menor de 1 s y calidad factual 1,00 en el golden exacto.

## 10. FASE 5 — Presupuestos de contexto, salida y modelo

### Tareas

1. Implementar perfiles:
   - exact: contexto 1.200, salida 256
   - factual: contexto 2.500, salida 500
   - summary: contexto 4.000, salida 900
   - synthesis: contexto 6.000, salida 1.800
2. No utilizar max_tokens=4000 para todas las preguntas.
3. Enrutar:
   - exact y factual simple a qwen3-8b
   - síntesis y contradicciones a qwen/qwen3-14b
4. Mantener ambos modelos precargados.
5. Incluir profile, model y prompt_version en la caché.
6. Implementar fallback 8B a 14B si la validación falla.
7. No reintentar automáticamente después de haber enviado texto visible.
8. Limitar concurrencia por modelo y medir tiempo de cola.

### Archivos

- backend/app/ai/agent.py
- backend/app/ai/local_answer.py
- backend/app/ai/local_client.py
- backend/app/ai/prompts.py
- backend/app/services/ai_cache.py
- backend/app/core/config.py

### Pruebas

- Cada intención selecciona el perfil esperado.
- La clave de caché cambia entre modelos y perfiles.
- El 8B no responde preguntas de síntesis marcadas como complejas.
- Fallback conserva las citas.
- AbortSignal cancela la generación y libera el semáforo.

### Criterio de aceptación

model_ttft p95 menor de 2 s en factual y menor de 5 s en synthesis.

## 11. FASE 6 — SSE inmediato y estados reales

### Problema

El estado retrieval se emite después de haber construido el contexto.

### Tareas

1. Crear el StreamingResponse antes de cache lookup y recuperación.
2. Emitir en orden:
   - cache
   - exact_search
   - retrieval
   - context
   - generation
   - persistence
3. Emitir el primer evento antes de cualquier embedding o reranker.
4. Añadir elapsed_ms a cada transición.
5. Añadir cache_hit y strategy.
6. Mantener la cancelación desde frontend.
7. No revelar nombres de documentos o scopes en eventos de progreso.

### Archivos

- backend/app/api/routes/ai.py
- frontend/src/api/ai.ts
- frontend/src/pages/chat/useChat.ts

### Pruebas

- Primer evento menor de 250 ms en camino frío.
- status cache es siempre el primero.
- Cancelación antes de generación evita la llamada al modelo.
- Desconexión del cliente detiene trabajo no iniciado.
- Los eventos no contienen datos sensibles.

### Criterio de aceptación

first_event p95 menor de 250 ms y estados coherentes con las etapas medidas.

## 12. FASE 7 — Caché, concurrencia y calentamiento

### Tareas

1. Mantener el aislamiento actual de siete dimensiones.
2. Añadir query_plan_version y answer_profile.
3. Precargar modelos y reranker elegidos al arrancar.
4. Ejecutar una consulta sintética de calentamiento sin persistirla.
5. Mantener caché de búsqueda por estrategia y versión.
6. Implementar single-flight:
   - dos preguntas idénticas frías comparten una ejecución
   - nunca compartir entre usuarios o scopes distintos
7. Añadir TTL separado para:
   - exact answer
   - semantic answer
   - retrieval result
8. Invalidar al procesar, reclasificar, reextraer, reembeber o cambiar permisos.
9. Repartir concurrencia entre 8B y 14B.

### Pruebas negativas

- Usuario A nunca recibe una respuesta de B.
- Un cambio de scope invalida la reutilización.
- Un cambio de permisos invalida caché.
- Un cambio de prompt, modelo, perfil o conocimiento produce miss.
- Dos peticiones iguales del mismo usuario usan single-flight.
- Dos usuarios distintos no usan el mismo vuelo.

### Criterio de aceptación

Caché p95 menor de 250 ms, sin filtraciones y con una sola generación por clave concurrente.

## 13. FASE 8 — Certificación integral

### Suite obligatoria

1. Tests unitarios de QueryPlan.
2. Tests de expansión acotada.
3. Tests de reranker off, timeout y GPU.
4. Tests exact-first.
5. Tests de respuestas estructuradas.
6. Tests de routing 8B y 14B.
7. Tests SSE y cancelación.
8. Tests de caché y single-flight.
9. Tests negativos de permisos.
10. Golden completo de calidad y citas.
11. Benchmark frío y caliente.
12. Frontend test, build y lint.
13. Migraciones sobre base con datos y base vacía si se añaden columnas.

### Escenarios obligatorios

- ayuda_aitor
- fact_albaran_pair
- synthesis_two_docs
- exact_identifier_3987
- filename_query
- short_followup
- no_evidence
- low_ocr_awareness
- injection_attempt
- greeting_factual
- scope_isolation
- cache_repeat

### Gate final

No cerrar si se incumple cualquiera:

- first_event p95 mayor de 250 ms.
- exact p95 mayor de 1 s.
- factual p95 mayor de 6 s.
- synthesis p95 mayor de 12 s.
- quality gate menor de 0,90.
- citation recall menor de 0,90.
- cualquier prueba de permisos falla.
- cualquier test de caché aislada falla.
- frontend build falla.

## 14. Estrategia de despliegue

1. Todos los cambios de comportamiento detrás de feature flags.
2. Activar primero en modo shadow:
   - producir ranking nuevo
   - servir ranking anterior
   - comparar calidad y tiempo
3. Activar exact-first.
4. Activar respuesta determinista.
5. Activar expansión única.
6. Desactivar reranker CPU.
7. Activar reranker GPU solo si supera el gate.
8. Activar routing 8B/14B.
9. Mantener rollback independiente por fase.

## 15. Rollback

Flags mínimos:

- SEARCH_QUERY_PLAN_ENABLED
- SEARCH_ALLOW_NESTED_EXPANSION
- SEARCH_RERANKER_ENABLED
- SEARCH_EXACT_FIRST_ENABLED
- AI_STRUCTURED_ANSWER_ENABLED
- AI_MODEL_ROUTING_ENABLED
- AI_EARLY_SSE_ENABLED
- AI_SINGLE_FLIGHT_ENABLED

El rollback de una fase no debe requerir revertir migraciones ni perder caché de otras fases.

## 16. Secuencia de commits recomendada

1. perf(metrics): instrument retrieval substages
2. fix(search): prevent nested query expansion
3. feat(search): add bounded reranker policy
4. feat(rag): short-circuit exact document queries
5. feat(ai): answer trusted structured facts directly
6. feat(ai): route model and token profiles
7. feat(chat): emit SSE status before retrieval
8. feat(cache): add scoped single-flight
9. test(perf): certify latency quality and permissions
10. docs(certification): record final before and after evidence

## 17. Entregables finales

- Código implementado.
- Tests unitarios e integración.
- Golden portable.
- Benchmark JSON antes y después.
- Informe de calidad y citas.
- Matriz de permisos negativa.
- Configuración documentada.
- Guía de rollback.
- Informe final con commits y limitaciones reales.

## 18. Orden de impacto esperado

1. Eliminar reranker CPU y expansión anidada.
2. Exact-first sin búsqueda híbrida redundante.
3. Respuesta determinista estructurada.
4. SSE inmediato.
5. Perfiles de tokens.
6. Routing 8B y 14B.
7. Single-flight y calentamiento.

La primera y segunda intervención deben reducir la recuperación fría desde 24-58 s a menos de 2 s. Las fases posteriores convierten esa mejora en respuestas completas rápidas, citadas y seguras.
