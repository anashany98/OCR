# Brief para Mimo: chat documental universal y reducción de revisiones falsas

> Objetivo: cualquier usuario autorizado debe poder preguntar por cualquier dato presente en un documento y recibir respuesta basada en evidencia, aunque documento esté mal clasificado, número no aparezca en filename o falten entidades estructuradas. A la vez, reducir documentos enviados a revisión por fallos técnicos o reglas de calidad demasiado amplias.

## 0. Reglas de ejecución

- Repo: FastAPI + Celery + PostgreSQL/pgvector + Redis + React.
- Mantener contratos públicos de `BaseOCREngine`, `embed_many`, `embed_query_text` y `search_*`.
- Mantener política sin hash fallback silencioso.
- No excluir documentos de búsqueda por clasificación incorrecta.
- No mostrar como válida una respuesta documental sin evidencia persistible.
- Añadir tests por cada cambio de comportamiento.
- Añadir migración Alembic si cambia esquema.
- Un commit revisable por tarea: `CR1`, `CR2`, etc.
- No aprobar masivamente documentos antes de reparar OCR y recalcular calidad.
- Worktree contiene cambios en curso del pipeline. Revisar `git diff` y no sobrescribir trabajo ajeno.

---

# 1. Incidentes confirmados

## 1.1 Documento real de aceptación

Documento:

```text
ID: 1249
Archivo: hoja 9 instalacion faldones.pdf
Ruta: /app/data/input/2025/ARABELLA HOTELS SL/Presupuesto 251044/PDF/hoja 9 instalacion faldones.pdf
Tipo actual: muestra_tela
Estado: processed
Calidad: processed_ok
Página: 1
Motor: pymupdf
Confianza OCR: 1.0
Chunks: 3
Embeddings: 3/3
```

Texto relevante:

```text
DOCUMENTO
260025
ORDEN DE TRABAJO
12/01/2026
SHERATON FALDONES
Fecha 12/01/25
Instalación de faldones con velcro...
```

Preguntas que fallaron:

```text
¿Qué sabes del presupuesto 260025?
```

El sistema respondió que no existía.

```text
¿Qué sabes del documento hoja 9 instalacion faldones?
¿De qué fecha es?
```

Primera pregunta recuperó contenido; seguimiento saltó a factura ajena con fecha 12-sep.-25.

## 1.2 Fallos confirmados en logs

```text
AI response rejected: unknown document number '260025'
```

```text
ForeignKeyViolation:
insert or update on table "ai_answer_sources"
block_id ... is not present in table "document_blocks"
```

La respuesta se transmite antes del commit final. Cuando persistencia de fuentes falla:

- UI conserva texto transmitido.
- Evento final con fuentes no llega correctamente.
- Aparece `Sin fuentes`.
- Respuesta no queda persistida.
- Contexto conversacional no queda persistido.
- Siguiente pregunta se ejecuta como búsqueda global.

## 1.3 Revisión documental actual

Foto de situación observada:

```text
Documentos totales: 1481
processed: 875
needs_review: 399
failed: 85
duplicate: 117
```

Flags dominantes entre `needs_review`:

```text
low_ocr_confidence: 289
page_without_text: 267
business_extraction_needs_review: 148
document_type_unknown: 129
budget_number_missing: 40
order_number_missing: 15
supplier_missing: 15
invoice_date_missing: 8
```

275 documentos en revisión tienen al menos una página vacía. 553 páginas pendientes usan `ocr_engine="empty"`.

## 1.4 Fallos OCR confirmados

```text
Permission denied: /app/data/files/..._pages/page_1_dpi300.png
```

```text
PaddleOCR (Tier 2) disabled: no GPU visible and paddleocr_gpu_only=true
```

```text
AttributeError: 'NoneType' object has no attribute 'extract'
```

La cascada llama `self.fallback.extract(...)` aunque fallback puede ser `None`.

---

# 2. Contrato funcional objetivo

## 2.1 Chat

Si dato existe en texto, tabla, entidad, filename o ruta de documento autorizado, sistema debe encontrarlo sin depender de clasificación.

Orden de recuperación:

```text
identificadores exactos
→ documento/filename/ruta
→ tablas estructuradas
→ búsqueda léxica/BM25
→ búsqueda semántica
→ fusión/reranking
→ carga de contexto
→ respuesta con fuentes
```

Regla obligatoria:

```text
No encontrado en tabla estructurada != no encontrado en documentos
```

## 2.2 Revisión

Separar:

- Fallo técnico bloqueante.
- Riesgo de seguridad bloqueante.
- OCR realmente ilegible.
- Documento utilizable con advertencias.
- Falta de campos estructurados no bloqueante.
- Documento visual sin texto esperado.

Documento con texto útil debe poder consultarse aunque:

- Tipo sea desconocido.
- Falte número estructurado.
- Falte relación con presupuesto/pedido.
- Una minoría de páginas tenga baja confianza.
- Sea foto de producto sin OCR textual.

---

# BLOQUE A — Reparar fuentes y sesión

## CR1 · No abortar respuesta por `block_id` obsoleto

### Archivos

- `backend/app/api/routes/ai.py`
- `backend/app/ai/agent.py`
- `backend/app/services/search_service.py`
- `backend/app/services/cache.py`
- Tests AI/SSE/fuentes.

### Problema

Resultados de búsqueda pueden conservar `block_id` eliminado tras reprocesado. Persistencia de `AIAnswerSource` viola FK y aborta transacción completa.

### Cambio requerido

Antes de crear `AIAnswerSource`:

1. Validar que `block_id` existe.
2. Validar que pertenece a `document_id` y página citados.
3. Si no existe, persistir fuente con `block_id=None` conservando documento, página y excerpt.
4. Registrar métrica `ai_source_stale_block_total`.
5. Invalidar caché de búsqueda/IA cuando se sustituyen `DocumentBlock` o `DocumentChunk`.
6. No permitir que una fuente degradada aborte respuesta completa.

Crear helper compartido, por ejemplo:

```python
def sanitize_source_reference(db, source) -> SanitizedSource:
    ...
```

Usarlo tanto en endpoint streaming como no streaming.

### Aceptación

- Fuente con bloque eliminado se guarda con `block_id=NULL`.
- Respuesta conserva documento, página y excerpt.
- Evento SSE `end` llega con fuentes.
- No se produce `ForeignKeyViolation`.

## CR2 · Persistencia tolerante y orden correcto

### Problema

Respuesta se transmite antes de confirmar persistencia. Fallo posterior deja texto visible sin historial, fuentes ni sesión.

### Cambio requerido

- Preparar y sanear fuentes antes de comenzar stream cuando sea posible.
- Persistir respuesta y fuentes sin depender de contexto conversacional.
- Persistir contexto en operación separada y tolerante.
- Si persistencia final falla, emitir evento SSE explícito de error; frontend no debe presentar respuesta como completa con `Sin fuentes`.
- Añadir `answer_id` al tipo `AIStreamEvent.end` del frontend.
- Registrar `ai_stream_persist_failure_total{stage}`.

No duplicar commits sin necesidad; diseñar transacciones claras:

```text
respuesta + fuentes → commit
contexto de sesión → commit independiente/best effort
cache → best effort
```

### Aceptación

- Respuesta visible existe en historial.
- Evento final contiene `answer_id` y fuentes.
- Fallo de sesión no borra respuesta.
- Fallo de fuente individual no borra respuesta.

## CR3 · Contexto por conversación, no global

### Archivos

- `frontend/src/pages/chat/useChat.ts`
- `backend/app/ai/active_context.py`
- `backend/app/ai/reference_resolver.py`
- `backend/app/api/routes/ai.py`

### Problema

Frontend usa una única clave global `docu-intel:chat:session-id`; conversaciones distintas pueden compartir estado. Seguimientos cortos sin pronombre no se resuelven.

### Cambio requerido

- Usar `Conversation.id` como `session_id` estable para esa conversación.
- Nueva conversación → nuevo `session_id`.
- Cambiar conversación → recuperar su propio contexto.
- Añadir detección de follow-up elíptico:
  - `¿De qué fecha es?`
  - `¿Qué importe tiene?`
  - `¿Quién lo instala?`
  - `¿Cuántas unidades?`
  - `¿Y el cliente?`
  - `¿Y el proveedor?`
- Si existe `current_document_id`, resolver estas preguntas contra documento activo.
- Si no existe contexto inequívoco, pedir aclaración; nunca ejecutar respuesta global como si correspondiera al documento anterior.

### Aceptación

- Después de resolver documento 1249, `¿De qué fecha es?` consulta solo 1249.
- Abrir nueva conversación no hereda documento 1249.
- Dos conversaciones mantienen contextos distintos.

---

# BLOQUE B — Búsqueda universal

## CR4 · Búsqueda exacta de identificadores

### Archivos

- Nuevo `backend/app/services/exact_document_search.py` o integración limpia en `search_service.py`.
- `backend/app/ai/tools.py`
- `backend/app/ai/context.py`
- `backend/app/tools/search.py`

### Cambio requerido

Detectar identificadores de pregunta:

- Números de documento.
- Presupuesto.
- Pedido/orden.
- Factura.
- Albarán.
- Referencia.
- CIF/NIF.
- Teléfono, cuando usuario lo pide explícitamente.

Buscar exacto y normalizado en:

- `documents.original_filename`
- `documents.source_path`
- `document_pages.text`
- `document_blocks.text`
- `document_chunks.chunk_text`
- `document_entities.entity_value`
- Tablas `budgets`, `orders`, `invoices`, `delivery_notes` y equivalentes reales.

Para números, usar límites que eviten parciales incorrectos:

```regex
(?<!\d)260025(?!\d)
```

Normalizar separadores, prefijos y ceros sin perder valor original.

La búsqueda exacta debe tener prioridad sobre semántica. Si encuentra coincidencia única autorizada, fijar `resolved_doc_id`.

### Aceptación

- `¿Qué sabes del presupuesto 260025?` encuentra documento 1249.
- Funciona aunque filename no tenga `260025`.
- Funciona aunque `document_type` sea `muestra_tela`.
- Coincidencia parcial `26002` no selecciona `260025`.

## CR5 · Fallback universal cuando tabla estructurada falla

### Problema

`get_budget_by_number` busca tabla `Budget`; si falla, fallback actual se limita principalmente a filename/ruta.

### Cambio requerido

Cuando búsqueda estructurada no encuentra registro:

1. Buscar número exacto en contenido documental.
2. Buscar entidades genéricas.
3. Ejecutar búsqueda léxica con identificador aislado, no pregunta completa.
4. Ejecutar semántica como apoyo.
5. Si encuentra documento, explicar:

```text
No existe fila estructurada como presupuesto, pero número aparece en documento X.
```

No responder `no encontrado` hasta agotar estas capas.

### Aceptación

- Ausencia en tabla no bloquea documento con texto coincidente.
- Advertencia diferencia coincidencia documental de entidad estructurada.

## CR6 · Clasificación nunca limita recuperación

### Cambio requerido

- `document_type` puede aumentar relevancia, nunca excluir coincidencia exacta.
- Aplicar filtros de tipo solo cuando usuario los exige explícitamente.
- Si pregunta dice `presupuesto` pero coincidencia exacta está clasificada como otro tipo, devolverla con advertencia de clasificación.
- Corregir clasificación/extracción de órdenes de trabajo como documento 1249.

Entidades genéricas recomendadas:

```text
document_number
work_order_number
document_date
reference
customer_name
supplier_name
location
```

### Aceptación

- Documento mal clasificado sigue siendo recuperable.
- Reprocesado de entidades no obliga a repetir OCR.

## CR7 · Fusión y contexto de documento completo

### Cambio requerido

- Añadir señal exacta a RRF/reranker con prioridad superior.
- Para coincidencia exacta única, cargar texto completo si documento es corto.
- Para documento largo, cargar página coincidente + páginas vecinas.
- Mantener límites de contexto y deduplicación.
- No mezclar documentos en seguimiento fijado salvo petición explícita global.

### Aceptación

- Número exacto no pierde contra coincidencias semánticas vagas.
- Seguimiento usa documento activo sin contaminación de facturas externas.

---

# BLOQUE C — Respuestas con evidencia

## CR8 · Fuentes obligatorias para afirmaciones documentales

### Cambio requerido

System prompt y validador:

- Toda fecha, importe, número, cantidad, cliente o proveedor debe apoyarse en fuente.
- Respuesta debe incluir documento y página.
- Si documentos presentan valores incompatibles, citar ambos y señalar inconsistencia.
- Si no hay fuente suficiente, responder que no hay evidencia; no completar desde conocimiento general.
- Si pregunta está fijada a documento, rechazar menciones a otros documentos no presentes en contexto.

Para documento 1249, respuesta esperada:

```text
La cabecera indica 12/01/2026. En la descripción aparece también
“Fecha 12/01/25”, por lo que el documento contiene una inconsistencia.
Fuente: hoja 9 instalacion faldones.pdf, página 1.
```

### Aceptación

- Nunca responde `12-sep.-25` desde factura ajena.
- UI muestra chip de documento/página.
- Inconsistencia se conserva, no se resuelve arbitrariamente.

---

# BLOQUE D — Reparación OCR y revisión documental

## CR9 · Reparar permisos de renderizado

### Archivos

- `docker-compose.yml`
- `docker-compose.prod.yml`
- Entrypoint/backend Docker.
- `backend/app/services/file_storage.py`
- `backend/app/parsers/pdf.py`

### Cambio requerido

- Garantizar mismo UID/GID con escritura en `data/files` para backend y workers.
- Revisar directorios existentes creados con propietario/modo incompatible.
- Entrypoint debe reparar solo rutas gestionadas necesarias, sin `chmod 777` indiscriminado.
- Crear directorios `*_pages` con permisos consistentes.
- Healthcheck de escritura controlada al arrancar worker OCR.
- Fallo de escritura debe marcar error técnico explícito; no crear página silenciosamente `empty` como si OCR fuera malo.

### Aceptación

- Cero `Permission denied` al renderizar lote de prueba.
- Preview y OCR usan archivo generado correctamente.
- Fallo de permisos se clasifica `technical_failure`, no `low_ocr`.

## CR10 · Activar PaddleOCR GPU y sanear cascada

### Archivos

- `docker-compose.yml`
- `backend/app/ocr/cascading.py`
- `backend/app/ocr/factory.py`
- `backend/app/workers/celery_app.py`

### Cambio requerido

- Verificar servicios GPU realmente iniciados.
- Una RTX 4070 por worker mediante `CUDA_VISIBLE_DEVICES`.
- Confirmar PaddleOCR activo cuando `paddleocr_gpu_only=true`.
- Si fallback es `None`, no llamar `.extract()` ni `.name`.
- Warmup con fixture de imagen válido; no `/dev/null`.
- Exponer health/metric de tiers disponibles.

### Aceptación

```text
ocr_tier_available{tier="tesseract"}=1
ocr_tier_available{tier="paddleocr"}=1
```

- Cero `NoneType` en cascada.
- Warmup no genera warning por imagen inválida.

## CR11 · Rediseñar política de revisión

### Archivos

- `backend/app/services/quality.py`
- `backend/app/services/business_extraction.py`
- `backend/app/services/plan_extraction.py`
- Modelos/esquemas/API de work inbox.

### Cambio requerido

Separar `review_required` de `quality_warnings`.

Bloqueantes:

- `security_quarantine`
- `technical_failure`
- `page_failed`
- Documento textual sin texto tras OCR válido.
- OCR ilegible en mayoría de páginas.

No bloqueantes por defecto:

- `document_type_unknown` con texto suficiente.
- `business_extraction_needs_review` con texto disponible.
- Campo estructurado ausente.
- `partial_low_ocr_confidence` cuando mayoría es legible.
- Foto/muestra visual sin texto esperado.
- Plano sin escala cuando texto sigue consultable.

Estados sugeridos:

```text
processed_ok
usable_with_warnings
needs_human_review
technical_failure
security_quarantine
failed
```

Corregir autoaprobación en `quality.py`: primera asignación `processed_ok` no debe ser sobrescrita por segundo `if` independiente.

No usar mínimo OCR como único valor global. Evaluar:

- Ratio de páginas bajas.
- Longitud/densidad de texto.
- Páginas vacías esperables.
- Tipo visual/textual.
- Fallos técnicos separados.

### Aceptación

- Email con texto útil y campos faltantes no bloquea.
- Foto de producto no se marca como OCR fallido.
- PDF de 10 páginas con 1 página dudosa sigue consultable con advertencia.
- PDF textual vacío sí requiere revisión.

## CR12 · Reprocesado y backfill seguro

### Orden obligatorio

1. Reparar permisos.
2. Confirmar tiers OCR.
3. Reprocesar documentos con `page_without_text`/`ocr_engine=empty`.
4. Reprocesar `page_failed`.
5. Recalcular calidad sin OCR para documentos con texto existente.
6. Reextraer entidades/reclasificar sin OCR cuando texto ya existe.
7. Medir reducción de cola.

### Cambio requerido

- Comando dry-run con conteos por motivo.
- Batch configurable.
- Checkpoint/idempotencia.
- No repetir OCR para simples cambios de calidad o clasificación.
- Registrar antes/después por documento.

### Aceptación

- No se aprueban silenciosamente documentos realmente vacíos.
- No se repite OCR de documentos con texto válido al recalcular calidad.
- Informe final muestra:
  - corregidos,
  - siguen en revisión,
  - fallaron,
  - motivo restante.

---

# 3. Tests obligatorios

## Chat/RAG

1. Número solo en `DocumentPage.text`.
2. Número solo en `DocumentChunk.chunk_text`.
3. Número solo en entidad estructurada.
4. Documento mal clasificado.
5. Filename aproximado con error ortográfico (`insralacion`).
6. Documento sin embedding pero con texto.
7. Documento sin fila `Budget` pero coincidencia textual.
8. `block_id` obsoleto al persistir fuente.
9. Follow-up `¿De qué fecha es?` con documento activo.
10. Follow-up sin estado pide aclaración.
11. Conversaciones independientes no comparten contexto.
12. Valor inconsistente cita ambas variantes.
13. Afirmación documental siempre tiene fuente.

## OCR/calidad

1. Directorio no escribible produce `technical_failure` claro.
2. Fallback `None` no rompe cascada.
3. Foto sin texto no se marca como OCR textual fallido.
4. Email útil con campo faltante queda `usable_with_warnings`.
5. Una página baja entre diez no bloquea documento.
6. Mayoría de páginas vacías sí bloquea.
7. Recalcular calidad no repite OCR.
8. Reprocesado por batch es idempotente.

## Test E2E de aceptación: documento 1249

```text
Usuario: ¿Qué sabes del presupuesto 260025?
```

Debe:

- Encontrar documento 1249.
- Explicar que `260025` figura como número de documento/orden de trabajo.
- Indicar relación de carpeta con `Presupuesto 251044` sin confundir ambos números.
- Describir instalación de faldones en Hotel Sheraton.
- Citar página 1.

```text
Usuario: ¿De qué fecha es?
```

Debe:

- Mantener documento 1249.
- Mostrar `12/01/2026` y `12/01/25`.
- Advertir inconsistencia.
- No consultar factura ajena.
- Persistir respuesta y fuente.

---

# 4. Métricas

Añadir:

- `exact_document_search_total{kind,outcome}`
- `exact_document_search_latency_seconds`
- `ai_source_stale_block_total`
- `ai_stream_persist_failure_total{stage}`
- `ai_followup_resolution_total{kind,outcome}`
- `ai_answers_without_sources_total{reason}`
- `review_documents_total{reason,severity}`
- `review_auto_resolved_total{reason}`
- `ocr_render_permission_failure_total`
- `ocr_tier_available{tier}`

Evitar IDs, filenames o números documentales como labels Prometheus.

---

# 5. Orden de commits

| Orden | Commit | Contenido |
|---:|---|---|
| 1 | `CR1` | Sanear fuentes y bloquear FK obsoleta |
| 2 | `CR2` | Persistencia SSE tolerante |
| 3 | `CR3` | Contexto por conversación y follow-ups cortos |
| 4 | `CR4` | Búsqueda exacta universal |
| 5 | `CR5` | Fallback documental tras fallo estructurado |
| 6 | `CR6` | Clasificación no restrictiva + entidades genéricas |
| 7 | `CR7` | Fusión/carga de contexto |
| 8 | `CR8` | Fuentes obligatorias y consistencias |
| 9 | `CR9` | Permisos de renderizado |
| 10 | `CR10` | Paddle GPU, cascada y warmup |
| 11 | `CR11` | Política de revisión |
| 12 | `CR12` | Backfill/reprocesado seguro |

CR9/CR10 deben completarse antes de ejecutar CR12, aunque commits de chat puedan desarrollarse en paralelo sin mezclar cambios.

---

# 6. Checklist final

- [ ] `260025` encuentra documento 1249 por contenido exacto.
- [ ] Tipo `muestra_tela` no impide recuperación.
- [ ] `¿De qué fecha es?` permanece en documento activo.
- [ ] Respuesta señala dos fechas incompatibles.
- [ ] Fuente incluye documento 1249 y página 1.
- [ ] Ningún bloque obsoleto aborta respuesta.
- [ ] Respuesta visible queda persistida en historial.
- [ ] Conversaciones no comparten contexto.
- [ ] No hay `Permission denied` al renderizar.
- [ ] PaddleOCR GPU aparece disponible.
- [ ] Cascada tolera fallback ausente.
- [ ] Campos faltantes no bloquean documento con texto útil.
- [ ] Fotos no generan falsas revisiones OCR.
- [ ] Reprocesado se ejecuta después de reparar infraestructura.
- [ ] Tests existentes y nuevos quedan verdes.

# 7. Entrega esperada de Mimo

Por tarea:

1. Diagnóstico confirmado contra código actual.
2. Archivos modificados.
3. Migración, si corresponde.
4. Tests ejecutados y resultado.
5. Evidencia antes/después.
6. Riesgos y rollback.
7. Commit independiente con prefijo indicado.

No dar tarea por terminada solo porque test unitario pase. Ejecutar E2E con documento 1249 y verificar respuesta, fuentes, historial y seguimiento conversacional desde UI.
