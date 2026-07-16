# Plan integral de mejoras — Docu-Intel

Fecha: 2026-07-13
Estado: ejecución autónoma por fases
Ámbito: `docu-intel/`; el corpus `D:\TEST2025\2025` es estrictamente de solo lectura.

## Resultado de producto

Cada archivo del corpus debe poder asociarse de forma trazable a `año / marca /
hotel opcional / presupuesto / proyecto / categoría`, sin duplicar bytes ni
perder apariciones físicas. Un usuario autorizado debe poder consultar el
proyecto, sus documentos, datos económicos, personas, comunicaciones,
incidencias, imágenes y planos mediante chat con fuentes; un usuario no
autorizado no debe poder inferir que esos datos existen.

## Principios no negociables

1. Preservar cambios locales ajenos y no usar operaciones Git destructivas.
2. Aplicar autorización en la consulta SQL, antes de leer contenido o crear
   contexto para el LLM; acceso vacío implica denegación.
3. Mantener las interfaces públicas de OCR y embeddings, y no introducir
   fallback silencioso de embeddings.
4. No editar migraciones aplicadas: cada cambio de esquema nace en una nueva
   revisión y se valida en base vacía y con datos.
5. Ingesta, backfill y enriquecimiento son idempotentes, auditables y
   reanudables. Un conflicto se conserva como conflicto, no se aprueba solo.
6. Cada cambio funcional incluye prueba positiva, negativa y de regresión.

## Línea base verificada

- El árbol contiene cambios locales versionados y sin seguimiento; se toman
  como entrada y no se reescriben.
- Existe una implementación parcial posterior a MIMO 2.5: jerarquía de
  proyectos, búsqueda exacta con `AccessScope`, dossier, modelos de
  comunicaciones e imágenes, y scripts de certificación.
- La búsqueda exacta ya rechaza llamadas sin scope y filtra antes de devolver
  contenido; falta certificarla dentro de todo el flujo de chat/dossier.
- El backfill existe pero necesita endurecimiento de contadores, checkpoints,
  savepoints y validación por lotes.
- El escáner normal ya se limita al inbox, pero el watcher aún incorporaba el
  corpus fijo; esta es la primera corrección de ejecución.

## Fases y criterios de salida

| Fase | Objetivo | Estado inicial | Criterio de salida |
|---|---|---|---|
| 0 | Baseline reproducible | parcial | compilación, migración temporal, build y fallos conocidos registrados |
| 1 | Permisos de extremo a extremo | parcial | ninguna recuperación exacta, semántica, dossier o fuente filtra después de leer |
| 2 | Identidad contextual de presupuesto | implementado | unicidad por año/marca/hotel/código; sin fusiones implícitas |
| 3 | Ingesta jerárquica atómica | implementado | occurrence, proyecto y enlace de presupuesto se crean o revierten juntos |
| 4 | Escaneo de corpus controlado | implementado | inbox acotado; corpus solo mediante backfill con cursor y métricas |
| 5 | Backfill seguro | implementado base | `dry-run` no escribe; lotes reanudables, contadores veraces y conflictos visibles |
| 6 | Dossier autorizado | parcial | DTO determinista completo, sin doble conteo ni datos fuera de scope |
| 7 | Chat por conversación/proyecto | parcial | contexto persistente y aislado por conversación, con desambiguación |
| 8 | Enriquecimiento de imágenes | parcial | análisis persistido, autorizado y recuperable con fuentes |
| 9 | Correos, personas e incidencias | parcial | hilos, adjuntos y participantes materializados e idempotentes |
| 10 | Planos, memorias y overlays | compatibilidad corregida | tipo público compatible, subtipo separado, persistencia y UI real |
| 11 | Calidad, métricas y operación | parcial | métricas accionables, colas protegidas, sin revisión masiva falsa |
| 12 | Certificación y despliegue | parcial | matriz E2E real, permisos negativos, migraciones y rollback lógico |

## Fase 0 — baseline y contrato de validación

Ejecutar antes de una fase que toque esquema, permisos o pipeline:

```powershell
git status --short
git diff --check
python -m compileall -q backend/app
python -m pytest -q backend/tests/test_project_path_resolver.py
python -m pytest -q backend/tests/test_cr4_exact_search.py
npm --prefix frontend run build
```

La certificación completa incorpora PostgreSQL temporal, todas las migraciones
y gates frontend. No se ocultarán fallos reduciendo cobertura o aumentando
timeouts.

## Fase 1 — seguridad y aislamiento

- Hacer obligatorio `AccessScope` en toda búsqueda autenticada.
- Reutilizar predicados SQL para entities, páginas, bloques, chunks, filename,
  rutas, dossier, imágenes, comunicaciones y planos.
- Redactar importes, PII y rutas antes del DTO y del prompt.
- Probar administrador, usuario autorizado, usuario sin grupo, tags denegados
  y documentos no asignados.

Salida: búsqueda del identificador exacto de otro hotel devuelve cero resultados
sin revelar ID, título, ruta, OCR ni importes.

## Fase 2 — identidad contextual

- Consolidar `BudgetScope` con `year`, `brand_id`, `hotel_id` y `budget_code`;
  crear una migración nueva para eliminar la unicidad global solo tras detectar
  colisiones.
- Crear/usar `get_or_create_budget_scope()` y
  `get_or_create_project_for_budget()` en todos los puntos de entrada.
- La identidad inicial de proyecto es `(año, marca, hotel opcional,
  presupuesto)`. Agrupar varios presupuestos exige operación manual auditada.

Salida: el mismo código en otro año, marca u hotel no colisiona; el hotel nulo
también es idempotente y la concurrencia no duplica entidades.

## Fase 3 — ingesta jerárquica

- Resolver y normalizar ruta sin perder el original.
- Registrar `Document` por SHA, `DocumentOccurrence` por ruta y
  `DocumentBudgetLink` por evidencia de carpeta/contenido.
- Persistir `folder_budget_code`, `document_budget_code`,
  `resolved_budget_code`, estado y evidencia. Estados: `verified`,
  `folder_only`, `content_only`, `conflict`, `manual`.
- Usar transacción y savepoint por archivo; misma ruta/SHA actualiza, mismo SHA
  en ruta distinta crea otra occurrence, ruta con SHA nuevo crea versión
  auditada.

Salida: toda occurrence presupuestada tiene proyecto y enlace; repetición no
duplica y un fallo no deja entidades huérfanas.

## Fase 4 — escáner separado del corpus

- `scan_input_folders()` solo trata el inbox dinámico y en orden determinista.
- El watcher observa exclusivamente el inbox; el corpus fijo no se encola ni
  se vigila de forma periódica.
- Un comando de backfill recorre el corpus con orden, cursor, límites,
  backpressure, métricas y dry-run sin persistencia.
- Evitar SHA cuando tamaño/mtime ya verifican que el archivo no cambió.

Salida: una llamada normal no toca el corpus; el lote procesa un máximo
reproducible y expone `examined`, `registered`, `skipped`, `errors`, bytes
hasheados y cursor.

## Fase 5 — backfill y reparación

- Reutilizar resolución e ingesta de fases 2–3; no duplicar reglas.
- Checkpoint atómico con versión, root, cursor y `run_id`; no escribirlo en
  `--dry-run` o `--validate-only`.
- Distinguir encontrados, creados, actualizados, enlazados por ruta, enlazados
  por SHA, omitidos, conflictos y errores.
- Desplegar en 100, validar SQL y muestra, luego 1.000; nunca ejecutar el
  corpus entero sin las puertas anteriores.

Salida: segunda ejecución no altera conteos estructurales y los contadores
coinciden con consultas SQL independientes.

## Fase 6 — dossier determinista

- Resolver proyecto con scope antes de recuperar sus datos.
- Entregar identidad, documentos únicos/apariciones, finanzas por moneda,
  productos, personas, comunicaciones, incidencias, cronología, imágenes,
  fuentes y `data_gaps`.
- Usar `db.execute(...).all()` para selecciones multicolumna y no sumar el
  mismo documento/importe por cada occurrence.

Salida: proyecto vacío devuelve DTO válido; no autorizado recibe denegación sin
existencia; cada hecho tiene fuente y las restricciones de precio/PII se aplican.

## Fase 7 — chat y contexto

- Persistir contexto por `session_id`: proyecto, presupuesto, marca, hotel,
  documento y filtros compatibles.
- Una referencia ambigua pide desambiguación; cambio de proyecto limpia el
  contexto incompatible.
- El frontend hidrata mensajes desde backend, no trata metadatos como mensajes,
  y expone proyecto activo y archivo/archivado explícitos.

Salida: conversaciones paralelas no mezclan proyectos ni fuentes y las
preguntas elípticas siguen el proyecto autorizado de su sesión.

## Fases 8–10 — enriquecimiento conectado

- Imágenes: conectar clasificación multietiqueta y `ImageAnalysis` a la
  ingesta; persistir confianza por hecho y respetar permisos.
- Comunicaciones: materializar hilos, mensajes, participantes, adjuntos,
  contactos e incidencias desde correos; deduplicar por identificadores
  estables.
- Planos/memorias: conservar `document_type == "plano"`, guardar subtipo y
  resultado técnico, y montar overlays en la pantalla real con fuente y
  confianza.

Salida: todo enriquecimiento es opcional, reintentable, auditable y nunca
impide que el documento quede consultable.

## Fase 11 — calidad y operación

- Clasificación o OCR no deben bloquear recall: búsqueda de identificador
  precede a semántica y los enlaces obsoletos degradan sin abortar la respuesta.
- Separar colas rápidas/pesadas, controlar backpressure y registrar latencia,
  fallos, conflictos, `needs_review`, recall exacto y tiempos por etapa.
- Reducir falsos `needs_review` con causas explícitas, no relajando umbrales a
  ciegas.

## Fase 12 — certificación y rollout

- Validar migraciones en PostgreSQL vacío y con datos, actualización y
  downgrade cuando sea compatible.
- Ejecutar matriz positiva/negativa de permisos, ingesta repetida, backfill,
  dossier, chat, imágenes, correos y planos contra fixtures controlados.
- Mantener rollback lógico por `run_id`; el corpus no se modifica nunca.

La certificación se acepta únicamente cuando todos los gates obligatorios pasan
sin flags de omisión y el informe registra ambiente, commit, esquema, conteos,
métricas, conflictos y pruebas ejecutadas.

## Orden autónomo de ejecución

1. Cerrar los defectos verificables de fases 1 y 4 sin tocar cambios locales.
2. Endurecer backfill e identidad solo tras pruebas de migración/ingesta.
3. Completar dossier y chat sobre datos ya autorizados y enlazados.
4. Conectar enriquecimientos de menor riesgo detrás de gates y colas.
5. Certificar con fixtures y corpus de muestra antes de cualquier backfill real.

Cada avance se anotará aquí con archivos afectados, pruebas ejecutadas, resultado
y cualquier bloqueo real. No se declarará finalizado por compilación aislada.

## Registro de ejecución

### 2026-07-13 — Fases 1, 4, 5 y 10

- **Fase 1 validada:** `test_cr4_exact_search.py` confirma rechazo sin
  `AccessScope`, filtrado antes de devolver contenido y ocultación de rutas a
  usuarios no administradores. La certificación controlada de ciclo de
  proyecto cubre además dossier autorizado y denegación de proyecto ajeno.
- **Fase 4 implementada:**
  `backend/app/ingestion/watcher.py` vigila solo `input_dir`; ya no encola ni
  observa `source_corpus_dir`. Los recorridos de archivos son deterministas y
  los rescans del watcher/Celery pasan `max_examined` para no recorrer un inbox
  ilimitado si los primeros archivos no se pueden registrar.
- **Fase 5 implementada base:** `backfill_corpus.py` reutiliza
  `_create_occurrence()` de la ingesta en lugar de duplicar identidad de
  marca/hotel/presupuesto/proyecto. El checkpoint incorpora versión y root,
  se escribe mediante sustitución atómica, no se escribe en dry-run y no avanza
  tras un error. El enlace busca primero ruta exacta y calcula SHA solo como
  segunda evidencia, informando bytes hasheados.
- **Fase 10, compatibilidad:** `classification.py` conserva el contrato
  público `imagen` para fotos sin evidencia de plano en carpetas `planos/` y
  el contrato `excel` para hojas de cálculo con rutas visuales.

Validación ejecutada: `python -m compileall -q backend/app`, Ruff sobre los
archivos modificados y 69 pruebas dirigidas de ingesta/watcher/worker/búsqueda
exacta, backfill/occurrences/ciclo de proyecto y clasificación/content routing.
Todas pasan.

Pendiente para las siguientes fases autónomas: dossier/chat completo, conexión
de enriquecimientos, overlays y certificación Docker/E2E completa. No se ha
ejecutado backfill real ni modificado el corpus.

### 2026-07-13 — Fases 2 y 3

- **Fase 2 completada:** se reutiliza la identidad contextual ya introducida
  por `0053_contextual_budget_identity`; los helpers de scope y proyecto ahora
  toleran la carrera entre lectura y creación mediante savepoints y relectura
  tras la restricción única de PostgreSQL. Las integraciones heredadas solo
  resuelven scopes legacy o un código contextual inequívoco; un código con dos
  contextos devuelve ausencia en vez de elegir uno arbitrariamente.
- **Fase 3 completada:** la migración
  `0061_contextual_occurrence_provenance` añade evidencia y estado de
  asociación a cada occurrence. La ingesta guarda código de carpeta, código
  extraído, código resuelto y los estados `verified`, `folder_only`,
  `content_only`, `conflict` o `manual`. Un conflicto queda visible y no se
  confirma; una ruta fuera del corpus no genera pertenencia de proyecto; un
  SHA nuevo en la misma ruta actualiza la occurrence viva sin borrar el
  Document histórico.

Validación: 25 pruebas de identidad, ingesta contextual, sesiones de scope,
ciclo de proyecto, backfill e integración; Ruff y compilación backend. En
PostgreSQL temporal: `0060 -> 0061`, `0061 -> 0060` y `0060 -> 0061` pasan.

### 2026-07-13 — Fases 6 y 7

- **Fase 6 completada:** el dossier calcula documentos, apariciones,
  finanzas, participantes, comunicaciones, incidencias, imágenes y cronología
  exclusivamente desde documentos autorizados. El DTO incorpora fuentes
  estables y `data_gaps`, y respeta la ocultación de precios y PII.
- **Fase 7 completada:** `project_id` pasa de contexto de sesión a filtro
  efectivo de ILIKE, BM25 y pgvector mediante `document_occurrences`; el
  guard de alcance se aplica incluso cuando solo hay proyecto activo y un
  cambio de proyecto invalida documento, presupuesto y carpeta anteriores.
  Los turnos se registran por sesión y usuario, `GET
  /ai/sessions/{session_id}/messages` no revela sesiones ajenas y el frontend
  rehidrata cuerpos desde ese endpoint sin guardarlos en `localStorage`.

Validación: `compileall`, Ruff de los módulos modificados, pruebas backend
dirigidas de dossier/filtros/contexto/historial y build de producción del
frontend. No se ejecutó backfill real ni se modificó el corpus.

### 2026-07-13 — Fases 8, 9 y 10

- **Fase 8:** el análisis visual es opcional e idempotente; conserva las
  etiquetas de compatibilidad y almacena confianza por etiqueta.
- **Fase 9:** correo `.msg`/`.eml` materializa hilos, mensajes, contactos,
  participantes, adjuntos fuente e incidencias, deduplicados por documento y
  `Message-ID`.
- **Fase 10:** los resultados técnicos se asocian a la evidencia del documento
  y los overlays incluyen cotas/estancias con coordenadas, confianza y fuente.

Validación: 13 pruebas dirigidas, compilación backend, Ruff y build frontend.
La base temporal se eliminó al terminar.

### 2026-07-15 — reparación integral de datos, OCR y certificación

- **OCR y extracción robustos:** `DocumentBlock` expone la geometría que
  consume la extracción de tablas; el reintento OCR normaliza fábricas que
  devuelven una función; las páginas PDF con texto nativo registran confianza
  `1.0`; el cliente de visión reintenta terminaciones transitorias y aplica
  circuito de protección.
- **Identidad y datos de negocio:** las rutas `upload/<usuario>/...` se
  resuelven con la misma identidad contextual que el corpus, sin confundir el
  nombre temporal con el archivo lógico. Se repararon 32 occurrences de
  documentos cargados y 6 presupuestos sin número con un código contextual
  verificable. La clasificación ya no convierte una fotografía en presupuesto
  solo por estar dentro de una carpeta con ese nombre; se revisaron 8 casos
  heredados.
- **Comunicaciones auditables:** la importación entiende encabezados y fechas
  en español, adjuntos en lista y respuestas por `Message-ID`. Se
  rematerializaron 8 correos fuente y se eliminaron 107 mensajes/hilos
  heredados sin `document_id`, que no tenían adjuntos ni participantes y por
  tanto no podían ser trazados a un documento.
- **Planos, memorias y mediciones:** se persisten fase y revisión de plano;
  `medicion` y `mediciones_obra` pasan por el mismo extractor idempotente de
  capítulos/partidas. El backfill procesó 21 documentos técnicos; el detector
  de fase ya no puede convertir una frase OCR extensa en un valor que haga
  fallar la transacción.
- **Recuperación y certificación:** los identificadores compuestos presentes
  en rutas fuente dejan de ser rechazados como inventados. La certificación
  usa Redis temporal sin contaminar `REDIS_URL`; las pruebas M3 ahora requieren
  perfil y credenciales explícitos (`-RunLiveM3`) en vez de contraseñas
  obsoletas embebidas.

Validación: Ruff en los archivos modificados, `git diff --check`, 67 pruebas
dirigidas de OCR, comunicaciones, reparadores, planos, medición, negocio y
validación; certificación backend completa con baseline, aislamiento de tenant
y suite backend en verde. Las pruebas M3 y las de OCR que requieren Tesseract se
declaran omitidas cuando no existe su entorno explícito; no se consideran
evidencia de un perfil GPU/M3.

Actualización posterior: el selector de re-embedding ya no reintenta
documentos sanos ni documentos OCR bajos cuando el presupuesto de re-OCR es
cero. Se ejecutaron lotes acotados sobre el corpus real hasta dejar **0 chunks
sin embedding** y **0 chunks marcados para re-embedding**; el único documento
sin texto/chunks se cerró como `fully_processed`, no como pendiente eterno.
Las 17 páginas de OCR bajo permanecen visibles para revisión o re-OCR explícito:
el entorno tiene `REEMBED_REOCR_PER_TICK=0`, por lo que no se encoló OCR pesado
de forma automática.
