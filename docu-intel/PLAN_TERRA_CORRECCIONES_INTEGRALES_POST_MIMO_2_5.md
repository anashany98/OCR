# Plan ultra detallado para Terra — corrección integral posterior a MIMO 2.5

## 0. Encargo y resultado obligatorio

- Repositorio: `C:\Users\Usuario\Desktop\OCR\OCR\docu-intel`
- Corpus fijo e inmutable: `D:\TEST2025\2025`
- Destinatario: **Terra**
- Base funcional: `PLAN_MIMO_2_5_CORRECCIONES_INTEGRALES.md`
- Commit auditado: `1436601 feat(M25): ejecucion integral plan MIMO 2.5`
- Alcance: commit anterior más cambios locales posteriores todavía sin confirmar.

Este documento es una orden de ejecución. Una fase no está terminada porque compile, porque existan tablas o porque pase una prueba aislada. Solo termina cuando su implementación está conectada al flujo real, respeta permisos, es idempotente cuando corresponde y supera sus pruebas positivas y negativas.

Sin mover ni renombrar carpetas, la aplicación debe interpretar:

```text
año / marca / [hotel opcional] / Presupuesto <código> / tipo documental / archivo
```

Cada aparición física debe quedar relacionada con año, marca, hotel opcional, presupuesto, proyecto, categoría y ruta original. El mismo SHA puede aparecer en varios proyectos sin duplicar bytes ni perder pertenencias.

El gestor debe poder preguntar en el chat: de qué trata el proyecto; qué documentos lo forman; presupuesto, pedidos, albaranes y facturas; productos, partidas, cantidades y precios; qué se hizo; problemas e incidencias; conversaciones y adjuntos; personas, gestores y comerciales internos/externos; imágenes, zonas, productos y estado de instalación. Cada afirmación relevante debe tener fuente y respetar permisos antes de llegar al LLM.

## 1. Estado confirmado en la auditoría

### Correcto actualmente

- Backend compila y frontend construye.
- Servicios Docker aparecen saludables.
- La base registra Alembic `0052_image_analysis`.
- Existen modelos de proyecto, apariciones, líneas de factura, comunicaciones e imágenes.
- El frontend envía `Conversation.id` como `session_id`.

### Incompleto o incorrecto

1. La búsqueda exacta ignora `access_scope`.
2. La ingestión guarda `DocumentOccurrence.project_id=None`.
3. No crea `DocumentBudgetLink`.
4. `BudgetScope.budget_code` sigue siendo único globalmente.
5. El backfill agrupa por marca/hotel/año e ignora presupuesto.
6. El dossier usa `db.scalars()` incorrectamente en consultas multicolumna.
7. El dossier no aplica toda la política de acceso.
8. Los campos de proyecto de `ActiveContext` nunca se rellenan.
9. El frontend carga metadatos de conversación como si contuvieran mensajes.
10. `ImageAnalysis` y `classify_image_multilabel()` no están conectados.
11. No se materializan conversaciones/personas desde correos.
12. El escáner recorre repetidamente los 31.323 archivos.
13. Los subtipos `plano_*` rompen consumidores que esperan `plano`.
14. `technical_pipeline.py` no persiste y no está conectado.
15. Los overlays no están montados en la pantalla real.
16. El supuesto E2E no ingiere veinte proyectos reales.
17. `npm run test` falla por cobertura.

Evidencia observada:

```text
documents=9
projects=3
document_occurrences=0
communication_threads=0
communication_messages=0
image_analyses=0
```

## 2. Reglas obligatorias para Terra

1. Ejecutar al comenzar: `git status --short`, `git diff --check`, `git log -5 --oneline`.
2. No borrar, sobrescribir ni reformatear cambios locales ajenos.
3. Prohibido `git reset --hard`, limpiezas masivas o borrar el corpus.
4. Un commit pequeño por tarea terminada.
5. Revisar el diff completo antes de tocar archivos ya modificados.
6. No romper `BaseOCREngine.extract`, embeddings ni búsquedas públicas.
7. No depender del filename hash almacenado para clasificar.
8. No convertir silenciosamente `BudgetScope` en `Project`.
9. No fusionar proyectos por cliente, proveedor o similitud semántica.
10. Aplicar permisos antes de recuperar datos, no al final.
11. No añadir dependencias sin `requirements.txt`, Docker y prueba de importación.
12. Cada tarea exige prueba positiva, negativa, regresión e idempotencia cuando aplique.
13. Migraciones: probar base vacía y base con datos.

## 3. Arquitectura objetivo

```text
Ruta fija
  -> ProjectPathResolver
  -> Brand/Hotel/BudgetScope contextual/Project/categoría
  -> Document por SHA + DocumentOccurrence + DocumentBudgetLink
  -> Parse/OCR -> clasificación -> extracción estructurada
  -> economía + comunicaciones + imágenes + planos/memorias
  -> chunks/embeddings
  -> dossier determinista autorizado
  -> chat con ActiveContext por conversación/proyecto
  -> respuesta grounded con fuentes
```

# 4. Plan de ejecución

## FASE 0 — Línea base reproducible

### Objetivo

Evitar validar contenedores construidos con código antiguo y conocer los fallos previos.

### Áreas

`docker-compose.yml`, `backend/Dockerfile`, `backend/docker-entrypoint.sh`, `backend/alembic/`, `backend/tests/`, `frontend/package.json`, `frontend/vite.config.ts`.

### Tareas

1. Documentar commit, dirty files, versión de esquema, conteos DB, servicios y pruebas.
2. Reconstruir servicios cuyo código no esté montado como volumen, especialmente Alembic.
3. Crear PostgreSQL temporal para migraciones completas.
4. No ejecutar todavía el backfill real.
5. Ejecutar:

   ```powershell
   python -m compileall -q backend/app
   python -m pytest -q backend/tests/test_project_path_resolver.py
   python -m pytest -q backend/tests/test_classification.py
   python -m pytest -q backend/tests/test_mass_ingestion.py
   npm --prefix frontend run build
   npm --prefix frontend run test
   ```

6. No esconder bloqueos aumentando timeouts sin diagnosticar.

### Entregable y aceptación

Crear `docs/TERRA_BASELINE_POST_MIMO_2_5.md`. Los contenedores deben ejecutar el árbol actual, Alembic importar todas las revisiones y los fallos iniciales quedar registrados. Commit: `test(baseline): make post-MIMO validation reproducible`.

## FASE 1 — Cerrar fuga de permisos

### Archivos

`services/exact_document_search.py`, `ai/context.py`, `services/project_dossier.py`, `services/tenant_access.py`, `services/source_sanitizer.py`, `tests/test_cr4_exact_search.py` y nuevo `tests/test_project_dossier_access.py`.

### Búsqueda exacta

1. Hacer obligatorio `access_scope` desde chat autenticado.
2. Filtrar en SQL documentos autorizados antes de buscar en entidades, páginas, bloques, chunks, filename o ruta.
3. Respetar admin, `allow_all_hotels`, chain/hotel IDs, tags, tipos permitidos, documentos sin asignar y deny-by-default.
4. Scope vacío bajo deny-by-default devuelve cero resultados.
5. No crear `ExactMatch`, `ContextItem` o `resolved_document` con datos no autorizados.
6. No exponer `source_path` cuando la política de rutas no lo permita.
7. Métricas: `found`, `not_found`, `forbidden_filtered`, `ambiguous`.

### Dossier

1. Crear `require_project_access(db, project, access_scope)`.
2. Aplicar scope a `resolve_project`, dossier, documentos, finanzas, personas, comunicaciones, incidencias e imágenes.
3. Comprobar cada documento, no solo la marca/hotel del proyecto.
4. Redactar importes y PII antes de DTO/prompt.

### Pruebas y aceptación

- Usuario Hotel A encuentra A, pero al buscar número exacto de B obtiene cero.
- No se filtran ID, filename, path, OCR, entidades ni importes de B.
- Scope vacío ve cero; admin ve ambos.
- Gestor sin precios ve documento con importes redactados.
- Tag denegado prevalece sobre hotel permitido.
- No queda ninguna llamada autenticada a exact search sin scope.

Commit: `fix(security): enforce access scope before exact and project retrieval`.

## FASE 2 — Identidad contextual de presupuesto/proyecto

### Decisión de dominio

Como no existe carpeta física de proyecto adicional, usar inicialmente:

```text
Project = año + marca + hotel opcional + presupuesto contextual
```

No agrupar varios presupuestos automáticamente. Una agrupación futura debe ser manual, explícita y auditada.

### Migración nueva posterior a 0052

No editar migraciones aplicadas. Añadir a `budget_scopes`: `year`, `brand_id`, `hotel_id`, `context_key` y, si conviene, `legacy_unscoped`. Eliminar la unicidad global solo después de analizar colisiones. Crear unicidad contextual PostgreSQL 16 con tratamiento de nulos, por ejemplo:

```sql
CREATE UNIQUE INDEX uq_budget_scope_context
ON budget_scopes (year, brand_id, hotel_id, budget_code) NULLS NOT DISTINCT;
```

En `projects`, identidad determinista `(year, brand_id, hotel_id, primary_budget_scope_id)` con hotel nulo controlado.

### Servicios

Implementar y reutilizar:

```python
get_or_create_budget_scope(db, year, brand_id, hotel_id, budget_code)
get_or_create_project_for_budget(db, year, brand_id, hotel_id, budget_scope_id)
```

Prohibir búsquedas internas solo por `budget_code`. Si el chat encuentra varios contextos, debe mostrar año/marca/hotel para desambiguar.

### Pruebas

- mismo contexto/código = mismo scope;
- otro año, marca u hotel = scope distinto;
- hotel nulo idempotente;
- concurrencia no duplica;
- upgrade/downgrade temporal;
- migración con colisiones simuladas;
- scopes heredados quedan identificados, no fusionados.

Commits: `feat(data): add contextual budget identity` y `feat(projects): enforce deterministic project identity`.

## FASE 3 — Ingestión jerárquica atómica

### Flujo en una transacción

1. Validar/normalizar ruta para análisis y conservar ruta exacta.
2. Resolver año, marca, hotel, código y categoría.
3. Obtener/crear marca y hotel dentro de marca.
4. Obtener/crear presupuesto contextual y proyecto.
5. Obtener/crear `Document` por SHA.
6. Crear/actualizar occurrence por `(source_root, source_path)`.
7. Guardar `project_id`, scope, marca, hotel, año, categoría.
8. Crear `DocumentBudgetLink` con evidencia de carpeta.
9. Mantener `Document.budget_scope_id` solo como enlace legado primario.
10. Confirmar todo junto; un error no deja entidades huérfanas.

### Deduplicación

- Mismo SHA/ruta: actualizar `last_seen_at`, no duplicar.
- Mismo SHA/ruta distinta: nueva aparición, mismo Document.
- Mismo SHA/presupuesto distinto: nueva aparición y link.
- Ruta igual/SHA cambiado: nueva versión con auditoría.
- Una pertenencia nueva nunca debe descartarse como duplicado inútil.

Persistir `folder_budget_code`, `document_budget_code`, `resolved_budget_code`, `association_status` y evidencia. Estados: `verified`, `folder_only`, `content_only`, `conflict`, `manual`. Nunca aprobar conflicto automáticamente.

### Pruebas y aceptación

- Registro nuevo crea una aparición y un link.
- Repetición no duplica.
- SHA repetido en dos presupuestos crea dos apariciones.
- Presupuesto directo deja hotel nulo.
- Categorías genéricas no se interpretan como código.
- Ruta fuera del root se rechaza.
- Conflicto queda pendiente.
- Todo occurrence con presupuesto tiene proyecto y link.

Commit: `fix(ingestion): atomically link documents to contextual projects`.

## FASE 4 — Escaneo controlado del corpus

Separar:

```python
scan_input_folders(...)       # solo input dinámico
scan_source_corpus_batch(...) # corpus fijo con cursor/lote
```

### Tareas

1. Quitar `source_corpus_dir` del escáner normal.
2. Crear comando/tarea de corpus independiente.
3. Usar orden determinista; no comparar checkpoint lexicográfico con `rglob()` sin ordenar.
4. Checkpoint atómico con root, versión y cursor; dry-run no lo escribe.
5. Límite por examinados y registrados, con métricas separadas.
6. Savepoint por archivo.
7. Respetar pausa/backpressure.
8. Evitar recalcular SHA si tamaño/mtime verificados no cambiaron.

### Pruebas

- `test_mass_ingestion.py` termina en menos de 30 s.
- Escáner input nunca toca el corpus.
- Lote procesa exactamente su límite.
- Reanudar no omite/repite.
- Dry-run no escribe DB/checkpoint.
- Error en archivo 50 conserva 1–49.
- Segunda ejecución no duplica.

Métricas: examinados, nuevos, sin cambios, bytes hasheados, tiempo, cursor, conflictos y errores. Commit: `fix(ingestion): separate bounded corpus scanning from inbox polling`.

## FASE 5 — Backfill seguro, reanudable y verificable

### Archivos

`commands/backfill_corpus.py`, `commands/backfill_reprocess.py`, nuevo `tests/test_backfill_corpus.py` y `commands/test_e2e_20_projects.py`.

### Tareas

1. Reutilizar los servicios de identidad e ingestión de FASE 2/3; no duplicar lógica.
2. Corregir contadores: tener `id` no significa que el objeto acaba de crearse.
3. Separar encontrados, creados, actualizados, omitidos, enlazados por ruta, enlazados por SHA, conflictos, errores y pendientes.
4. Enlazar primero por ruta exacta y usar SHA como segunda evidencia.
5. Filename solo nunca es evidencia definitiva.
6. No crear proyecto genérico por hotel/año; crear proyecto por presupuesto contextual.
7. Reporte JSON y resumen humano.
8. Añadir `--sample N` reproducible y `--validate-only`.
9. Dry-run no escribe DB ni checkpoint.
10. Usar lotes y savepoints; registrar `run_id` para auditoría/rollback lógico.

### Reparar el falso E2E

1. Verificar que las veinte rutas existen realmente.
2. No duplicar el segmento `2025` al construir rutas.
3. Comparar `expected_category`; actualmente solo se calcula.
4. Ingerir fixtures/controlados y verificar Document, occurrence, link, project y dossier.
5. Fallar si `occurrence_count == 0`.
6. Ejecutar dos veces y comprobar idempotencia.
7. No declarar correcta la lógica por coincidir con un conteo rígido de archivos.

### Despliegue por lotes

```text
1. --dry-run --limit 100
2. --execute --limit 100
3. validar SQL y muestra manual
4. --execute --limit 1000
5. validar conflictos/errores
6. continuar en lotes
```

### Aceptación

Repetir no cambia conteos estructurales; todas las apariciones presupuestadas tienen proyecto/link; contadores coinciden con SQL independiente; conflictos quedan visibles y no aprobados. Commit: `fix(backfill): make hierarchy population resumable and truthful`.

## FASE 6 — Dossier determinista completo

### Archivos

`services/project_dossier.py`, `models/project.py`, `models/business.py`, `models/communication.py`, `tools/internal.py`, `ai/tools.py` y nuevas pruebas.

### Reparación SQLAlchemy

Cuando se seleccionen dos columnas/modelos usar:

```python
rows = db.execute(stmt).all()
for occurrence, document in rows:
    ...
```

No usar `db.scalars()` si se necesitan varios valores.

### Herramientas obligatorias

1. `resolve_project`;
2. `get_project_dossier`;
3. `list_project_documents`;
4. `get_project_financials`;
5. `get_project_products`;
6. `get_project_people`;
7. `get_project_communications`;
8. `get_project_issues`;
9. `get_project_timeline`;
10. `search_project_images`.

### Contrato mínimo

```json
{
  "project": {},
  "identity": {"year": 2025, "brand": {}, "hotel": {}, "budgets": []},
  "description": {},
  "documents": {
    "unique_documents": 0,
    "occurrences": 0,
    "by_category": {},
    "missing_categories": []
  },
  "financials": {
    "budgets": [], "orders": [], "delivery_notes": [],
    "invoices": [], "totals": {}, "discrepancies": []
  },
  "products": [], "people": [], "communications": [],
  "issues": [], "timeline": [], "images": [],
  "data_gaps": [], "sources": []
}
```

### Reglas

- Distinguir documentos únicos de apariciones.
- Sumar todos los scopes asociados, no solo `primary_budget_scope_id`.
- Evitar duplicar importes por múltiples apariciones.
- No sumar monedas distintas.
- Productos conservan código, descripción, cantidad, unidad, precio y fuente.
- `participant_count` no puede quedar hardcodeado.
- Descripción determinista primero; resumen IA solo secundario y con fuentes.
- Datos ausentes se declaran en `data_gaps`; no se inventan.

### Pruebas

- Proyecto vacío devuelve DTO válido.
- Dos occurrences del mismo documento cuentan 1 documento/2 apariciones.
- Finanzas no se duplican.
- Sin permiso de precios se redacta.
- Sin acceso no se revela existencia.
- Consultas multicolumna funcionan.
- Cada hecho tiene fuente.

Commit: `feat(projects): deliver authorized deterministic project dossier`.

## FASE 7 — Chat por conversación y proyecto real

### Archivos

`ai/active_context.py`, `ai/context.py`, `ai/reference_resolver.py`, `ai/agent.py`, `api/routes/ai.py`, `models/chat_session.py`, `frontend/src/pages/chat/useChat.ts` y UI del chat.

### Backend

1. Extender `update_after_answer()` con `resolved_project`, `resolved_brand`, `resolved_hotel` y `resolved_budget_scope`.
2. Al resolver documento, derivar su occurrence autorizado y actualizar contexto.
3. Si hay varias apariciones autorizadas, pedir presupuesto/hotel.
4. `scope_filters()` prioriza `current_project_id` y `current_budget_scope_id`.
5. No confundir `current_budget_id` con `budget_scope_id`.
6. Cambiar proyecto limpia documento, factura, pedido, imágenes y resultados incompatibles.
7. Persistir mensajes/estado coherentemente.
8. Añadir endpoints de listar, recuperar y archivar conversaciones si faltan.

### Frontend

1. No cargar metadata-only como conversación completa.
2. Recomendado: metadatos locales y mensajes hidratados desde backend.
3. Como mínimo, inicializar `messages: []` y mostrar estado sin hidratar.
4. Añadir selector opcional de proyecto.
5. Mostrar proyecto activo, marca, hotel y presupuesto.
6. Nueva conversación = UUID y contexto vacío.
7. Cambiar conversación recupera contexto propio.
8. Borrar/archivar tiene semántica backend explícita.

### Conversaciones obligatorias

```text
Explícame el proyecto 252536.
¿Qué documentos tiene?
¿Y las facturas?
¿Qué productos lo componen?
¿Cuánto se presupuestó y facturó?
¿Quién intervino?
¿Qué problemas hubo?
Enséñame imágenes de la instalación.
Cambia al proyecto del Hotel X.
¿Y ahora qué facturas tiene?
```

### Pruebas

- Dos conversaciones mantienen proyectos distintos.
- Recargar no rompe `messages`.
- Follow-up usa proyecto activo.
- Cambiar proyecto limpia contexto anterior.
- Número ambiguo ofrece opciones.
- Número no autorizado no revela coincidencias.
- Respuesta cita fuentes del dossier.

Commit: `feat(chat): persist independent project context per conversation`.

## FASE 8 — Imágenes variables realmente integradas

### Archivos

`models/document.py`, `parsers/clip_classifier.py`, `parsers/image_taxonomy.py`, `parsers/image.py`, `parsers/router.py`, `services/document_processing_core.py`, nuevo `services/image_analysis_service.py` y dossier.

### Flujo

1. Combinar ruta original, carpeta, filename original, propiedades visuales, OCR, clasificador y VLM.
2. Invocar `classify_image_multilabel()` y combinar `classify_by_filename()` + `classify_by_folder()` + píxeles.
3. Elegir OCR-first, vision-only, OCR+vision o vision+OCR ligero.
4. Persistir `ImageAnalysis` con upsert.
5. Vigencia mínima: `document_id + file_hash + model_name + model_version + taxonomy_version`.
6. No recalcular VLM en cada pregunta.
7. Confianza por hecho; no inferirla solo por longitud de respuesta.
8. Persistir etiquetas, descripción, texto, objetos, materiales, colores, mediciones, referencias, zona, estado, incidencia, sensibilidad, embedding, pHash y procedencia.
9. Separar observación de inferencia.
10. Redactar datos sensibles antes de responder.

### Corpus visual mínimo

Producto, instalación, muestra material, croquis manuscrito, plano fotografiado, recibo/factura, captura, incidencia, render, logo, borrosa y desconocida.

### Pruebas/métricas

- Una imagen crea registro; segunda ejecución misma versión usa caché.
- Cambiar versión invalida controladamente.
- Buscar imágenes usa etiquetas, descripción, zona, producto e incidencia.
- Chat cita imagen fuente.
- Medir distribución de etiquetas, desconocidas, review, cache hit/miss, latencia, errores y precisión por clase.

Commit: `feat(images): persist cached multimodal analysis by project`.

## FASE 9 — Correos, conversaciones y personas

### Archivos

`parsers/msg.py`, `models/communication.py`, nuevo `services/communication_ingestion.py`, `services/document_processing_core.py`, dossier y fixtures `.msg/.eml` anonimizadas.

### DTO normalizado

```text
message_id, conversation_id, subject_normalized,
sent_at, from, to, cc, body_text,
attachment_names, in_reply_to, references
```

### Tareas

1. Crear contacto por email normalizado sin duplicados.
2. Dominio puede sugerir organización, nunca confirmarla sin evidencia.
3. Agrupar hilo por headers; asunto normalizado es fallback con confianza.
4. Enlazar thread al proyecto mediante occurrence/budget del correo.
5. Crear message, participantes y adjuntos.
6. Roles con evidencia/confianza: gestor interno, comercial interno, comercial externo, cliente, proveedor, arquitecto, instalador, técnico, desconocido.
7. No asignar rol definitivo únicamente por dominio.
8. Detectar eventos/incidencias con documento, mensaje, fecha y confianza.
9. Idempotencia por documento/message-id.
10. Aplicar permisos antes de mostrar asunto, participantes o cuerpo.

### Pruebas

- Dos mensajes del mismo hilo crean 1 thread/2 messages.
- Reprocesar no duplica.
- Forward sin headers no se fusiona arbitrariamente.
- Adjuntos se enlazan correctamente.
- Interno/externo se determina con configuración y evidencia.
- Incidencia conserva fuente.
- Usuario no autorizado no ve datos.

Aceptación: dossier muestra conversaciones reales, `participant_count` se calcula y chat responde quién intervino con fuentes. Commit: `feat(communications): materialize project threads participants and issues`.

## FASE 10 — Compatibilidad de planos y pipeline técnico

### Decisión recomendada

Mantener contrato público genérico y subtipo separado:

```text
Document.document_type = "plano"
Document.document_subtype = "arquitectura" | "estructura" | ...
```

Si no se añade columna, centralizar `is_plan_type()`, pero esto no soluciona por sí solo filtros SQL `document_type == "plano"`. La columna separada es preferible.

### Consumidores a revisar

`workers/routing.py`, `ai/tools.py`, `ai/context.py`, `services/data_quality.py`, `services/plan_extraction.py`, `services/quality.py`, `services/classification.py`, `services/technical_pipeline.py`.

### Persistencia técnica

1. Conectar `process_technical_document()` después de texto/clasificación.
2. Implementar la fase `Store`; no dejar dataclasses en memoria.
3. Planos: persistir Plan, habitaciones, cotas, símbolos, geometría, escala/revisión.
4. Memorias: capítulos, chunks jerárquicos y especificaciones con fuente.
5. Medición/presupuesto de obra: capítulos, partidas, descompuestos y totales.
6. Persistencia transaccional e idempotente.
7. Añadir scope a cada herramienta de `technical_chat.py` antes de conectarla.
8. Reemplazar `retrieve_context()` vacío por búsqueda híbrida autorizada.

### Pruebas

- Resolver la regresión de `test_classification.py` coordinadamente.
- Todo subtipo entra en cola pesada y se encuentra como `plano`.
- Extracción/calidad reconocen subtipos.
- Pipeline persiste sin duplicar.
- Herramientas técnicas no cruzan permisos.

Commits: `fix(plans): preserve generic plan contract while persisting subtypes` y `feat(technical): connect and persist technical extraction pipeline`.

## FASE 11 — Overlays y revisión humana

### Archivos

`frontend/src/pages/plano/usePlanOverlays.ts`, `components.tsx`, contenedor real del visor, `api/routes/plans.py` y pruebas React/API.

### Tareas

1. Montar el hook en el visor real.
2. Renderizar panel, cajetín, hechos del chat y revisiones en el SVG.
3. Unificar `OverlayVisibility`; no duplicar tipos.
4. Eliminar o usar el `documentId` actualmente ignorado.
5. Sustituir cajetín estático por datos extraídos o estado vacío explícito.
6. No presentar revisiones siempre vacías como función completa.
7. Conectar confirmar/rechazar/corregir con auditoría.
8. Probar transformación PDF/imagen -> SVG, zoom y pan.
9. Invalidar query keys correctas tras mutación.
10. Mostrar loading, error y empty state.

### Aceptación

El hook se usa desde pantalla; toggles funcionan; overlays mantienen coordenadas; confirmación actualiza DB/UI; usuario ajeno obtiene 404 sin datos. Commit: `feat(plans-ui): connect overlays and audited human review`.

## FASE 12 — E2E real, cobertura y observabilidad

### Niveles

#### Unitarias

Resolvedor, identidad, deduplicación, clasificación visual/planos, email y redacción.

#### Integración PostgreSQL

Migraciones, restricciones, registro, backfill, dossier, permisos, imagen y comunicaciones. No confiar solo en SQLite para pgvector, JSON, índices con NULL o concurrencia.

#### E2E

Tres proyectos controlados como mínimo:

1. marca -> presupuesto;
2. marca -> hotel -> presupuesto;
3. mismo SHA en dos presupuestos.

Cada conjunto debe combinar presupuesto, pedido, factura con líneas, correo, imagen y, cuando corresponda, plano/memoria.

### Escenarios

1. Ingestar sin mover carpetas.
2. Esperar hasta estado consultable.
3. Verificar jerarquía DB.
4. Consultar dossier.
5. Preguntar resumen y follow-up.
6. Cambiar conversación/proyecto.
7. Probar autorizado y no autorizado.
8. Repetir ingesta/backfill y demostrar idempotencia.

### Cobertura frontend

No bajar umbrales para hacer verde. Añadir pruebas de `useChat`, `usePlanOverlays`, selector, restauración, errores/vacíos y overlays. `npm run test` debe salir con código 0.

### Métricas/SLO iniciales

- 100 % occurrences presupuestados con proyecto/link.
- 0 fugas en matriz de permisos.
- 0 duplicados tras segunda ingesta.
- 100 % hechos económicos con fuente.
- 100 % hechos visuales con modelo/versión/confianza.
- 100 % mensajes con documento fuente.
- Escáner input de pruebas < 30 s.
- Dossier sin LLM < 2 s en proyecto mediano.
- Búsqueda exacta autorizada < 500 ms indexada.
- Medir por separado recuperación, espera de cola y generación.

### Comandos finales

```powershell
python -m compileall -q backend/app
python -m pytest -q backend/tests
npm --prefix frontend run build
npm --prefix frontend run test
docker compose run --rm migrate
docker compose ps
```

Además: E2E, permisos, migración vacía/con datos, dry-run, muestra real y segunda ejecución aprobadas. Commit: `test(e2e): prove authorized project lifecycle end to end`.

# 5. Orden obligatorio y dependencias

```text
0 baseline -> 1 seguridad -> 2 identidad -> 3 ingestión
-> 4 escaneo -> 5 backfill -> 6 dossier -> 7 chat
-> 8 imágenes + 9 comunicaciones -> 10 técnico
-> 11 frontend -> 12 E2E/rollout
```

- No conectar dossier/chat técnico al LLM antes de FASE 1.
- No ejecutar backfill completo antes de FASE 2–4.
- No declarar visión/comunicaciones terminadas si fixtures válidas no generan filas.

# 6. Migración, integridad y rollback

## Antes

1. Backup PostgreSQL.
2. Exportar conteos y colisiones de presupuesto.
3. Migrar copia de base.
4. Validar SQL.
5. Probar downgrade solo en temporal.

## Consultas mínimas

```sql
SELECT count(*) FROM documents;
SELECT count(*) FROM document_occurrences;
SELECT count(*) FROM document_budget_links;
SELECT count(*) FROM projects;

SELECT budget_code, count(*)
FROM budget_scopes
GROUP BY budget_code
HAVING count(*) > 1;

SELECT count(*) FROM document_occurrences
WHERE budget_scope_id IS NOT NULL AND project_id IS NULL;

SELECT count(*)
FROM document_occurrences o
LEFT JOIN document_budget_links l ON l.occurrence_id = o.id
WHERE o.budget_scope_id IS NOT NULL AND l.id IS NULL;
```

## Rollback lógico

- Etiquetar cada lote con `run_id`/auditoría.
- No borrar proyectos/scopes sin informe.
- Fallo de enriquecimiento conserva Document/Occurrence y reintenta etapa.
- Corpus siempre read-only.

# 7. Matriz mínima de permisos

| Rol | Permitido | Ajeno | Precios | PII | Rutas |
|---|---:|---:|---:|---:|---:|
| admin | sí | sí | sí | según política | sí |
| gestor autorizado | sí | no | según permiso | redactada | limitada |
| operario | limitado | no | normalmente no | redactada | limitada |
| auditor | lectura autorizada | no | según permiso | redactada | limitada |
| sin grupo | no | no | no | no | no |

Probar exacta, semántica, dossier, chat, imágenes, correos y planos.

# 8. Checklist por commit/PR

- [ ] Problema y contrato definidos.
- [ ] Diff acotado a una intención.
- [ ] Compatibilidad con datos existentes.
- [ ] Permisos antes de recuperar.
- [ ] Idempotencia.
- [ ] Prueba positiva, negativa y regresión.
- [ ] PostgreSQL real cuando aplica.
- [ ] Métricas sin datos sensibles.
- [ ] Migración/rollback documentados.
- [ ] No modifica corpus.

# 9. Estimación

Complejidad **alta**: seguridad, dominio, migraciones, ingestión, backfill, RAG, frontend y multimodal.

| Bloque | Tiempo con asistencia IA |
|---|---:|
| Baseline y seguridad | 1–2 días |
| Identidad, migración e ingestión | 3–4 días |
| Escáner y backfill | 2–3 días |
| Dossier y chat | 3–4 días |
| Imágenes | 2–4 días |
| Comunicaciones | 2–3 días |
| Planos/técnico/overlays | 3–5 días |
| E2E, cobertura y rollout | 2–3 días |

Total seguro: **18–28 días efectivos**. Entrega prioritaria de seguridad + jerarquía + dossier + chat: **10–15 días**. La IA acelera código/pruebas, no migración real, revisión de conflictos ni permisos.

# 10. Entregas

1. **A — Seguridad y datos confiables:** FASE 0–5.
2. **B — Consulta del proyecto:** FASE 6–7.
3. **C — Enriquecimiento:** FASE 8–11.
4. **D — Certificación:** FASE 12.

# 11. Definición final de terminado

Un gestor autorizado abre conversación, selecciona o nombra un proyecto real y obtiene con fuentes: explicación; marca/hotel/presupuesto; documentos; economía; productos/partidas; personas/roles; conversaciones/adjuntos; incidencias; imágenes; cronología; conflictos y datos faltantes.

Después cambia de conversación/proyecto sin mezclar contexto. Un usuario no autorizado que pregunta el mismo número no recibe evidencia de existencia. Repetir ingesta y backfill no crea duplicados ni cambia pertenencias verificadas.
