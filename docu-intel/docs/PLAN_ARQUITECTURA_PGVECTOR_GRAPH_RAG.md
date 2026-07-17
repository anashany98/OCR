# Plan de arquitectura — PostgreSQL + pgvector + Graph RAG relacional

> **Documento definitivo y vinculante.** Sustituye a cualquier plan previo
> (de esta rama o de sesiones anteriores) que mencionara Milvus, una segunda
> base de datos vectorial, una base de grafos independiente o una migración
> de embeddings fuera de PostgreSQL.
>
> **Auditoría de código:** 2026-07-16 · **Rama:** `codex/integracion-ovisocr2`
> · **Última migración:** `0063_ai_answer_fallback_reason` (la siguiente será `0064+`).
>
> Todas las afirmaciones técnicas de este documento están verificadas contra
> el código real del repositorio, no contra planes anteriores.

---

## 0. Decisión arquitectónica obligatoria (no negociable)

**Milvus queda completamente descartado para este proyecto.** Esta sección es
una lista exhaustiva de lo que **no se hará**, para que ningún agente de
código (MiniMax, Codex u otro) la reinterpretre como una mera preferencia:

**No se debe:**

- Instalar Milvus.
- Añadir Milvus a `docker-compose.yml`, `docker-compose.prod.yml` o cualquier
  otro compose.
- Crear conectores, clientes o adaptadores para Milvus.
- Migrar embeddings desde pgvector hacia otra base.
- Diseñar sincronización entre PostgreSQL y Milvus.
- Incluir Milvus como alternativa futura o "cuando escale".
- Preparar benchmarks de pgvector frente a Milvus.
- Añadir dependencias relacionadas con `pymilvus` (ni en
  `backend/requirements*.txt`, ni en `pyproject.toml`, ni en `services/*`).
- Utilizar Zilliz Cloud ni ningún servicio gestionado equivalente.
- Proponer una segunda base de datos vectorial de ninguna clase.

**Verificación de partida:** una búsqueda recursiva
(`grep -ril "milvus\|pymilvus\|zilliz" .`) confirma que **hoy no existe ni una
sola referencia** a Milvus en el repositorio. Este documento no "elimina"
código existente; **fija la prohibición** para que no se introduzca en el
futuro. Cualquier PR que añada `pymilvus`, un servicio `milvus` en compose o
una clase `Milvus*` debe rechazarse en revisión.

---

## 1. Arquitectura permitida — única fuente de verdad

La solución se construye exclusivamente con:

```text
PostgreSQL
+ pgvector
+ tablas relacionales normales
+ búsqueda textual de PostgreSQL (tsvector / GIN / ts_rank_cd)
+ búsqueda vectorial (HNSW sobre pgvector)
+ reranker local (BGE-reranker-v2-m3)
+ modelos locales (embeddings Granite 311M, LLM, OCR)
```

**Única fuente de verdad:**

```text
PostgreSQL
├── Datos de usuarios y permisos       (users, tenants, access_scope)
├── Documentos y páginas               (documents, document_pages)
├── Fragmentos OCR                     (document_chunks)
├── Embeddings mediante pgvector       (document_chunks.embedding,
│                                        documents.embedding,
│                                        document_pages.visual_embedding)
├── Entidades extraídas                (document_entities)
├── Relaciones entre entidades         (graph_relations — ver §3)
├── Evidencias documentales            (graph_relation_evidence)
├── Estados de revisión                (graph_review_queue)
└── Auditoría                          (audit_logs — ya particionada)
```

**Explícitamente fuera de la primera versión:** Milvus, Neo4j, Apache AGE,
Elasticsearch, OpenSearch, Pinecone, Weaviate, Qdrant, cualquier base
vectorial externa y cualquier base de grafos independiente. **Apache AGE queda
descartado** aunque sea una extensión de Postgres: el Graph RAG se modela con
tablas relacionales normales (§3), sin extensión de grafos.

---

## 2. Auditoría y optimización de pgvector

> Esta sección **sustituye** a la anterior "evaluación de Milvus", al
> "benchmark pgvector frente a Milvus", a los "contenedores de Milvus", a la
> "sincronización de embeddings" y a las "estrategias de migración hacia
> Milvus". No se compara pgvector con ninguna otra base vectorial: **se
> audita y se optimiza la configuración existente contra sí misma.**

### 2.1 Estado actual (verificado en código)

| Elemento | Estado real | Archivo / migración |
|---|---|---|
| Extensión `vector` | Instalada | `0008_vector_indexes.py` (`CREATE EXTENSION vector`) |
| Columna `document_chunks.embedding` | `Vector(768)`, nullable | `app/models/document.py:343` |
| Columna `documents.embedding` (nivel doc) | `Vector(768)`, dormida → activa vía `search_use_document_embedding=True` | `0002…/0042_document_level_embedding.py`, `config.py:405` |
| Columna `document_pages.visual_embedding` | `Vector(768)` | `app/models/document.py:442` |
| Modelo de embedding | `ibm-granite/granite-embedding-311m-multilingual-r2` (asimétrico, 768 dim) | `config.py:385`, `embeddings.py` |
| Distancia | **Coseno** (`vector_cosine_ops`) | `0008_vector_indexes.py:18` |
| Índice HNSW | `m=16`, `ef_construction=64`, `WHERE embedding IS NOT NULL` — **sólo en chunks** | `0008_vector_indexes.py:15-21` |
| `hnsw.ef_search` | **No se ajusta en ningún sitio** → usa el default de PG (40) | **Brecha — ver §2.3** |
| Índice IVFFlat | **No existe** | — (no se crea salvo justificación, §2.5) |
| `tsvector` BM25 | `to_tsvector('spanish', chunk_text)` persistido + GIN | `0039_chunks_tsv_spanish.py`, `document.py:366` |
| Reranker | Local BGE-v2-m3 + HTTP `/rerank`; **desactivado por defecto** (`search_reranker_enabled=False`) | `services/reranker.py`, `config.py:456` |
| Fusión híbrida | RRF (texto + semántico + bm25), `ThreadPoolExecutor(3)` | `services/search_service.py` |
| Prefiltro de permisos | **Obligatorio**: `PgvectorStore.search` exige `budget_scope_id`/`project_id` | `services/vector_store.py:33-44` |
| Particionado existente | `audit_logs` y `extraction_jobs` ya particionadas | `0033_partition_audit_and_jobs.py` |
| Coerción de dimensión | **Off** (`embedding_allow_dimension_coercion=False`) — correcto | `config.py:390` |

### 2.2 Dimensiones a medir (auditoría obligatoria antes de tocar parámetros)

Antes de cambiar `m`, `ef_construction`, `ef_search` o activar IVFFlat, hay
que caracterizar el sistema con datos reales. Medir y volcar en
`docs/INFORME_AUDITORIA_PGVECTOR_<fecha>.md`:

- Volumen actual de documentos (`SELECT count(*) FROM documents WHERE deleted_at IS NULL`).
- Número actual de chunks (`SELECT count(*) FROM document_chunks`).
- Crecimiento mensual estimado (delta de `documents.created_at` en los últimos 3 meses × proyección).
- Tamaño de los embeddings (`pg_total_relation_size('document_chunks')`, `pg_relation_size` del índice HNSW).
- Tamaño de los índices (`pg_size_pretty(pg_relation_size(c.oid))` joined con `pg_class`).
- Latencia **p50, p95 y p99** de `/search/hybrid` (con `EXPLAIN (ANALYZE, BUFFERS)` sobre la consulta vectorial).
- **Recall@5 y Recall@10** frente al golden set RAG (`backend/scripts/build_runtime_rag_golden.py` ya existe).
- Rendimiento con **7 consultas concurrentes** (cargar con `locust` o `asyncio.gather` contra `/search/hybrid`).
- Rendimiento **con filtros por permisos** (`budget_scope_id` + `project_id`) frente a sin filtros.
- Tiempo del reranker (local BGE-v2-m3) medido por `track_embedding_latency` equivalente en `reranker.py`.
- Tiempo total **hasta el primer token** del SSE de `/ai/ask/stream` (contrato fijado en `test_ai_stream_immediate.py`).

**Regla de no regresión:** ninguna optimización se mergea si empeora Recall@10
o si p95 de `/search/hybrid` sube más de un 10 % respecto al baseline medido en §2.2.

### 2.3 Parámetros a optimizar (orden de prioridad)

1. **`hnsw.ef_search`** — *brecha confirmada*. Hoy no se setea; el default 40
   puede ser alto (latencia) o bajo (recall) según el corpus. Añadir un
   parámetro `search_hnsw_ef_search` en `core/config.py` y ejecutar
   `SET LOCAL hnsw.ef_search = :ef` dentro de la transacción de
   `PgvectorStore._search_postgres` antes del `ORDER BY embedding <=> :q`.
   Barrer `ef_search ∈ {20, 40, 60, 80, 120}` midiendo p95 y Recall@10.
2. **`m` y `ef_construction`** del índice — hoy `m=16`, `ef_construction=64`.
   Sólo tocar si el paso 1 no alcanza el Recall@10 objetivo. `REINDEX` es
   costoso: planificar ventana de mantenimiento y medir antes/después.
3. **Tipo de distancia** — mantener **coseno** (`vector_cosine_ops`). Los
   embeddings Granite se normalizan (`normalize_embeddings=True`,
   `embeddings.py`), así que producto interno (`vector_ip_ops`) sería
   matemáticamente equivalente y algo más rápido; **sólo cambiar si el
   benchmark §2.6 lo justifica**, y exige `REINDEX` con ops distintas.
4. **Filtros previos por metadatos** — ya correctos y obligatorios en
   `PgvectorStore`. Revisar que el planner empuja los filtros dentro del scan
   HNSW (`EXPLAIN ANALYZE`); si no, añadir índices btree compuestos
   `(budget_scope_id)` / `(document_id, page_number)` sobre `documents`.
5. **Búsqueda híbrida texto + vector** — ya implementada (RRF). Ajustar el
   sobre-muestreo del pool de candidatos (hoy BM25 hace `limit*3`; alinear el
   pool vectorial al mismo factor para que el reranker reciba un campo
   comparable).
6. **Reranking** — activar `search_reranker_enabled=True` en dev **sólo
   después** del benchmark §2.6, si p95 ≤ 250 ms (criterio del informe
   `INFORME_CAMBIOS_PLAN_MAESTRO_2026-07-16.md` §Fase 3.2).
7. **Eliminación de duplicados** — la fusión RRF ya deduplica por
   `(document_id, page_number, block_id, chunk_id)`; verificar que el
   document-level embedding no doble-contabiliza.
8. **Límites de contexto** — mantener el tope de tokens del contexto IA;
   el reranker entrega `search_reranker_max_candidates=8` (config).
9. **Índices SQL complementarios** — `document_chunks(document_id, page_number)`
   ya existe; añadir `(embedding_model_version)` parcial si el sweep de
   re-embedding escanea mucho (ver `chunks_needing_model_migration`).
10. **Particionado** — **sólo si el volumen lo justifica** tras §2.2. Si
    `document_chunks` supera ~10 M de filas y p95 degrada, particionar por
    rango de `created_at` siguiendo el patrón de `0033`. No anticipar.
11. **Embeddings binarios** — **no implementar en esta fase.** Primero medir
    la calidad del sistema con los embeddings actuales (float32, 768 dim).

### 2.4 Búsqueda híbrida — estado y mejoras

La arquitectura híbrida ya existe y es correcta:

- `search_text` (ILIKE substring), `search_semantic` (pgvector coseno) y
  `search_bm25` (tsvector GIN + `ts_rank_cd` flag 32 = normalización BM25).
- Fusión por **RRF** (Reciprocal Rank Fusion) sin pesos por estrategia
  (decisión documentada en `bm25.py:52-67`).
- Paralelización con `ThreadPoolExecutor(max_workers=3)`.
- `search_singleflight.py` implementado y testeado pero **no integrado** en
  los endpoints (integrar cuando se observe carga con queries duplicadas;
  añadir `scope_key` explícito a las firmas públicas).

**Mejoras permitidas (sin salir de Postgres):** ajustar el over-fetch del
pool, alinear el `ef_search` de las tres ramas, activar el reranker bajo
umbral de latencia, y caché de resultados (`SEARCH_CACHE_TTL=60s` ya existe).

### 2.5 IVFFlat — sólo si está justificado

No existe índice IVFFlat hoy. **No se añade por defecto.** Se considera
**únicamente** si, tras §2.2/§2.3, el HNSW no cumple p95 y **el coste de
`REINDEX` de HNSW es prohibitivo** (índice > 50 % de RAM). En ese caso se
compararía `IVFFlat` con `lists ≈ √N` como rama del benchmark interno §2.6.
Mientras no se cumpla esa condición, IVFFLat queda fuera.

### 2.6 Benchmark interno (compara pgvector consigo mismo)

Diseñar un benchmark en `backend/scripts/benchmark_pgvector_configs.py` que,
sobre el **mismo** golden set y los **mismos** filtros de permisos, compare
**únicamente** estas seis configuraciones:

```text
1. pgvector sin índice aproximado     (SCAN + ORDER BY embedding <=>)
2. pgvector HNSW                      (m=16, ef_construction=64, ef_search variable)
3. pgvector IVFFlat                   (sólo si §2.5 lo activa)
4. búsqueda textual PostgreSQL        (search_bm25)
5. búsqueda híbrida texto + vector    (search_hybrid RRF, sin reranker)
6. búsqueda híbrida + reranker        (#5 + BGE-v2-m3)
```

Para cada configuración registrar: p50/p95/p99, Recall@5, Recall@10,
throughput con 7 concurrentes, tamaño del índice y tiempo hasta primer token.
**El benchmark no incluye ninguna base externa.** Su salida decide qué
configuración de pgvector queda en producción y qué valor de `ef_search` se
fija por defecto.

---

## 3. Graph RAG sobre tablas relacionales de PostgreSQL

El Graph RAG se implementa **únicamente** con tablas relacionales normales.
**Sin Neo4j, sin Apache AGE, sin extensión de grafos.** Las relaciones se
consultan con SQL estándar (`JOIN`, `EXISTS`, CTEs recursivas para vecinos).

### 3.1 Modelo de datos propuesto (migración nueva `0064+`)

Siete tablas, todas en PostgreSQL:

```text
graph_entities          — catálogo de entidades (proveedores, proyectos,
                         referencias, fechas, importes…) normalizadas y
                         deduplicadas. Reemplaza/prolonga document_entities
                         con identidad global por tenant.
graph_entity_mentions   — aparición de una entidad en un chunk/página/bloque
                         (múltiples menciones → una entidad). Soporta evidencia.
graph_relations         — relaciones verificadas entre dos entidades
                         (source_entity_id, target_entity_id, relation_type).
graph_relation_evidence — evidencia documental que respalda una relación
                         (document_id, chunk_id, quote, confidence).
graph_extraction_jobs   — jobs de extracción de entidades/relaciones
                         (idempotentes, reanudables).
graph_extraction_errors — errores de extracción por job (para reintentos).
graph_review_queue      — relaciones/entidades pendientes de revisión humana
                         (estado: pending / approved / rejected / escalated).
```

**Relación con lo existente:**

- `document_entities` (hoy, `app/models/document.py:311`) se conserva como
  extracción por-documento. `graph_entities` + `graph_entity_mentions` son la
  capa global: deduplican entidades que aparecen en varios documentos vía
  `normalized_value` (mecanismo ya usado en `document_graph.py:41-68` para
  unir documentos por referencia compartida).
- `document_graph.py` (98 líneas, grafo en memoria) queda como referencia; su
  lógica de `budget_order` y `shared_reference` se migra a filas de
  `graph_relations` generadas por el job de extracción.
- Particionado: `graph_relation_evidence` y `graph_extraction_errors` son
  candidatas a particionar por `created_at` si el volumen lo justifica
  (mismo patrón que `0033`). **No anticipar** hasta medir §2.2.

**Índices relacionales complementarios (planes de consulta típicos):**

- `graph_entities(tenant_id, normalized_value)` único parcial donde
  `normalized_value IS NOT NULL` (deduplicación por tenant).
- `graph_entity_mentions(entity_id)`, `(document_id, chunk_id)`.
- `graph_relations(source_entity_id, relation_type)`,
  `(target_entity_id)` — para recorrer el grafo en ambos sentidos.
- `graph_relation_evidence(relation_id)`, `(document_id)`.
- `graph_review_queue(status, created_at)` — para el panel de revisión.

### 3.2 Pipeline de extracción de relaciones

1. **Detección** — sobre documentos ya procesados (texto + entidades
   existentes), un extractor (modelo local o LLM con schema tipado vía
   `app/ai/structured_output.py`) propone pares
   `(entity, relation_type, entity)` con spans de evidencia.
2. **Verificación** — cada relación propuesta exige al menos una evidencia
   (`graph_relation_evidence`) con `quote` textual y `confidence`. Las que no
   alcanzan umbral van a `graph_review_queue`.
3. **Persistencia** — idempotente: re-ejecutar el job sobre el mismo documento
   no duplica filas (clave natural en `graph_relations`).
4. **Trazabilidad** — `graph_extraction_jobs` + `graph_extraction_errors`
   registran cada pasada; `audit_logs` (ya particionada) cubre quién aprueba
   qué en revisión.

### 3.3 Componentes de producto (sin nueva base de datos)

- **Router de consultas** — extender `app/ai/intent_router.py` (424 líneas,
  ya existe) para decidir si una pregunta del usuario activa recuperación
  híbrida (§2), recorrido del grafo (§3.2) o ambos. El grafo se consulta con
  SQL, no con un motor de grafos.
- **Panel de revisión** — endpoint admin que liste `graph_review_queue` y
  permita aprobar/rechazar; reutiliza `app/api/routes/admin_*` y
  `access_scope` existentes.
- **Evidencias** — la ficha de documento y el chat muestran las evidencias
  (`graph_relation_evidence.quote`) que respaldan cada relación citada, para
  auditoría humana.

---

## 4. Criterio de escalabilidad — orden de optimización

**No plantear otra base vectorial aunque el volumen aumente.** Si aparece un
problema de rendimiento, optimizar estrictamente en este orden, midiendo
antes/después de cada paso y documentando el resultado:

```text
 1. Consultas SQL            (EXPLAIN ANALYZE, reescribir SELECTs)
 2. Índices convencionales   (btree/GIN complementarios)
 3. Índice HNSW de pgvector  (ef_search primero; m/ef_construction después)
 4. Parámetros de recuperación (over-fetch del pool, top-k del reranker)
 5. Filtros previos por metadatos (budget_scope / project / tenant)
 6. Estrategia de chunking   (embedding_chunk_max_words, overlap)
 7. Reranker                 (activar/ajustar BGE-v2-m3)
 8. Caché                    (SEARCH_CACHE_TTL, single-flight)
 9. Réplicas de lectura de PostgreSQL
10. Particionado de tablas   (document_chunks, *_evidence, *_errors)
11. Mejora de hardware       (RAM, NVMe, GPU para embeddings/reranker)
```

El paso 12 **no existe**: no hay "migrar a otra base vectorial". La solución
final funciona exclusivamente con PostgreSQL y pgvector.

---

## 5. Recomendación final obligatoria

El documento **no elige entre bases vectoriales.** La recomendación
arquitectónica, única y final, es:

```text
Mantener PostgreSQL + pgvector como única plataforma de almacenamiento.

Implementar Graph RAG controlado mediante tablas relacionales normales
(graph_entities, graph_entity_mentions, graph_relations,
graph_relation_evidence, graph_extraction_jobs, graph_extraction_errors,
graph_review_queue).

Añadir extracción de entidades, relaciones verificadas, evidencias,
router de consultas y panel de revisión sin incorporar Milvus ni otra
base de datos adicional.
```

Prioridad del proyecto: **reducir complejidad operativa, mantener una única
fuente de verdad y aprovechar la infraestructura existente.** No sugerir
Milvus aunque técnicamente pudiera mejorar algún benchmark.

---

## 6. Checklist de ejecución (para el agente que implemente)

Cada ítem va en un commit aislado, con su test (patrones de `backend/tests/`,
sin requerir GPU/DB para CI local salvo el marcado).

- [ ] **0.** Confirmar con `grep -ril "milvus\|pymilvus\|zilliz" .` que sigue
      sin haber referencias a Milvus; el PR que añada cualquiera se rechaza.
- [ ] **1.** `feat(config)`: añadir `search_hnsw_ef_search` (default 40) en
      `core/config.py`.
- [ ] **2.** `perf(search)`: `SET LOCAL hnsw.ef_search` en
      `PgvectorStore._search_postgres`; test de contrato.
- [ ] **3.** `feat(scripts)`: `benchmark_pgvector_configs.py` (las 6 ramas
      de §2.6) + volcado a `docs/INFORME_AUDITORIA_PGVECTOR_<fecha>.md`.
- [ ] **4.** `docs`: informar dimensiones §2.2 (volumen, chunks, latencia,
      Recall@5/10, 7 concurrentes, filtros) sobre dev.
- [ ] **5.** `feat(db)`: migración `0064_graph_rag_relational` con las 7
      tablas de §3.1 + índices. Test de esquema.
- [ ] **6.** `feat(graph)`: extractor de relaciones idempotente con
      evidencia + `graph_extraction_jobs`/`graph_extraction_errors`.
- [ ] **7.** `feat(graph)`: panel de revisión sobre `graph_review_queue`
      (reutilizar `admin_*` + `access_scope`).
- [ ] **8.** `feat(ai)`: extender `intent_router.py` para enrutar a grafo
      (SQL) vs híbrido vs ambos.
- [ ] **9.** `feat(viewer)`: mostrar `graph_relation_evidence.quote` en la
      ficha de documento y en el chat (evidencias auditables).
- [ ] **10.** `docs`: actualizar `PLAN_MAESTRO_MEJORAS.md` y `AGENTS.md` con
       la prohibición de Milvus y el puntero a este documento.

**Reglas de ejecución:** commits atomizados con scope Conventional Commits;
no mezclar fases; no `git push` ni cambio de rama sin instrucción explícita;
respetar la densidad de comentarios y el idiom del código circundante
(FastAPI + SQLAlchemy 2.0 `select()`, Pydantic v2, settings tipados).
