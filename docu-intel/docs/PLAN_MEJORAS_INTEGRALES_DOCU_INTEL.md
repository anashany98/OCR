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
| 2 | Identidad contextual de presupuesto | parcial | unicidad por año/marca/hotel/código; sin fusiones implícitas |
| 3 | Ingesta jerárquica atómica | parcial | occurrence, proyecto y enlace de presupuesto se crean o revierten juntos |
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

Pendiente para las siguientes fases autónomas: migraciones contextuales sobre
PostgreSQL real, conflicto folder/contenido, dossier/chat completo, conexión de
enriquecimientos, overlays y certificación Docker/E2E completa. No se ha
ejecutado backfill real ni modificado el corpus.
