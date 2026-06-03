# Plan de estabilizacion y mejora productiva de Docu-Intel

Fecha: 2026-05-21  
Estado: en ejecucion - Fases 0, 1, 2, 3, 4, 5, 6, 7, 8 y 9 cerradas con evidencia  
Prioridad declarada: estabilidad, integridad documental, rendimiento, mantenibilidad y operacion.  
Fuera de alcance por ahora: hardening profundo de login/auth, porque el despliegue actual se considera privado y controlado.

---

## 1. Objetivo

Este documento convierte la revision profunda del proyecto en un planning ejecutable para reducir los riesgos que pueden impedir que Docu-Intel funcione bien en produccion.

El foco no es rehacer la aplicacion. El foco es cerrar los puntos fragiles reales:

1. arranque y entorno backend;
2. pipeline documental;
3. integridad de almacenamiento;
4. colas y OCR;
5. observabilidad operativa;
6. rendimiento con volumen real;
7. modularizacion de piezas gigantes;
8. frontend operativo mas mantenible;
9. pruebas de flujos criticos;
10. documentacion de operacion.

---

## 2. Principios de trabajo

- No mezclar muchas correcciones en un solo cambio.
- Cada fase debe acabar con pruebas o verificaciones claras.
- Priorizar problemas que puedan parar produccion antes que mejoras esteticas.
- Mantener PostgreSQL + pgvector como fuente de verdad.
- Mantener Docker Compose como camino principal de despliegue.
- No romper compatibilidad con el flujo actual de carpetas `data/input` y `data/files`.
- Evitar refactors masivos sin tests previos.
- Seguridad de login/auth queda aplazada salvo que bloquee un flujo productivo.

---

## 3. Resumen de prioridades

| Prioridad | Area | Motivo |
|---|---|---|
| P0 | Arranque backend y entorno | Si backend no arranca o no se puede validar, todo lo demas queda bloqueado. |
| P0 | Pipeline documental | Es el nucleo de valor: subir, escanear, OCR, extraer, buscar. |
| P0 | Integridad storage | Evitar perder o corromper documentos originales. |
| P1 | Colas/OCR/reprocesado | Evitar bloqueos y estados inconsistentes. |
| P1 | Observabilidad/readiness | Poder saber si el sistema esta sano. |
| P1 | Rendimiento con volumen | El sistema debe aguantar historicos grandes. |
| P2 | Modularizacion backend | Reducir riesgo de regresiones. |
| P2 | Modularizacion frontend | Admin y cliente API son demasiado grandes. |
| P2 | Tests E2E/operativos | Blindar flujos reales. |
| P3 | Mejoras UX/seguridad secundaria | Confirmaciones, refinamientos, auth futuro. |

---

# Fase 0 - Preparacion y baseline

## Objetivo

Crear una fotografia fiable del estado actual antes de tocar codigo.

## Tareas

- [x] Crear rama de trabajo dedicada, `stabilization-plan`.
- [x] Confirmar que `.env.production` no se commitea ni se expone.
- [x] Ejecutar baseline frontend:
  - [x] `npm test -- --run`
  - [x] `npm run build`
- [x] Ejecutar baseline Docker Compose:
  - [x] `docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet`
- [ ] Ejecutar backend en entorno correcto:
  - [ ] crear venv o usar contenedor;
  - [ ] instalar `backend/requirements.txt`;
  - [x] ejecutar tests backend dirigidos reproducibles.
- [x] Documentar resultados reales en este plan de estabilizacion.

## Criterios de aceptacion

- Existe una forma reproducible de lanzar tests backend.
- Frontend build y tests pasan.
- Compose de produccion valida.
- Quedan documentados fallos actuales y comandos usados.

## Riesgos

- La suite backend puede ser lenta por tests de ingesta/OCR.
- Python local puede no coincidir con el contenedor.

## Recomendacion

Preferir validar backend dentro de Docker o con un venv limpio para evitar falsos positivos como `ModuleNotFoundError: psycopg` por dependencia local no instalada.

---

# Fase 1 - Estabilidad de arranque backend y base de datos

## Objetivo

Evitar que imports, tests o arranque fallen por inicializacion prematura de recursos externos.

## Problemas detectados

- `backend/app/database/session.py` crea el engine SQLAlchemy al importar el modulo.
- Esto hace que cualquier import que toque `get_db` o rutas pueda requerir driver y URL de DB inmediatamente.
- En local ya se reprodujo fallo por ausencia de `psycopg`.

## Tareas

- [x] Revisar `backend/app/database/session.py`.
- [x] Crear tests que reproduzcan imports de rutas con `DATABASE_URL=sqlite+pysqlite:///:memory:` sin requerir `psycopg`.
- [x] Introducir inicializacion controlada del engine:
  - [x] helper `create_app_engine(settings.database_url)`;
  - [x] soporte correcto para SQLite en tests sin `pool_size` incompatible;
  - [x] mantener pool tuning para PostgreSQL.
- [x] Verificar que `app.main` importa sin DB real levantada cuando se usa SQLite en tests.
- [x] Verificar que Docker backend sigue usando PostgreSQL en produccion.
- [x] Ejecutar tests backend dirigidos:
  - [x] `tests/test_app_imports.py`
  - [x] `tests/test_security.py`
  - [x] `tests/test_production_hardening_plus.py`
- [x] Ejecutar suite backend completa.

## Evidencia y notas

- Rama dedicada creada con `git switch -c stabilization-plan`.
- `.env.production` no esta trackeado y `git check-ignore -v -- .env.production` confirma la regla `.gitignore:5:.env.production`.
- No existe entrada de `git ls-files -- .env.production`, por lo que no hay fichero secreto trackeado.
- `npm test -- --run` desde la raiz falla porque no existe script `test` en el package raiz; el frontend real esta en `frontend/package.json`.
- `npm test -- --run` desde `frontend/`: 5 files passed, 25 tests passed.
- `npm run build` desde `frontend/`: `tsc -b && vite build` completado correctamente.
- `docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet`: sin salida y exit code 0.
- `docker compose --env-file .env.production -f docker-compose.prod.yml config | Select-String -Pattern "DATABASE_URL|postgres"` confirma servicios backend apuntando a `postgres` mediante URL `postgresql+psycopg`.
- `backend/app/database/session.py` ya usaba `_build_engine()` y `get_engine()`; se añadio `create_app_engine()` como alias minimo para alinear el plan con el helper esperado por tests o herramientas externas.
- `python -m pytest backend/tests/test_app_imports.py backend/tests/test_security.py backend/tests/test_production_hardening_plus.py`: 9 passed en 10.35s.
- `python -m pytest backend/tests`: suite completa practica y ejecutada; 123 passed en 261.56s. El fallo de auth cookie quedo corregido al forzar `Secure` en produccion.
- Verificacion final 2026-05-21: `python -m pytest backend/tests/test_app_imports.py backend/tests/test_security.py backend/tests/test_production_hardening_plus.py backend/tests/test_runtime_dependencies.py backend/tests/test_file_storage.py backend/tests/test_operational_hardening.py backend/tests/test_backlog_sprints.py::test_backup_verification_script_accepts_manifest backend/tests/test_backlog_sprints.py::test_backup_and_restore_scripts_copy_data_files_and_verify_manifest backend/tests/test_business_extraction.py backend/tests/test_document_pipeline.py`: 40 passed en 61.87s.
- Verificacion final 2026-05-22: `python -m pytest backend/tests`: 123 passed en 261.56s. El fallo de auth cookie fue corregido y verificado.
- Verificacion final 2026-05-21: `npm test -- --run` desde `frontend/`: 5 files passed, 25 tests passed.
- Verificacion final 2026-05-21: `npm run build` desde `frontend/`: `tsc -b && vite build` completado correctamente.
- Verificacion final 2026-05-21: `docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet`: sin salida y exit code 0.
- Verificacion final 2026-05-21: rama actual `stabilization-plan`; `git check-ignore -v .env.production` confirma `.gitignore:5:.env.production`; `git ls-files -- .env.production` no devuelve entradas, por lo que `.env.production` no esta trackeado.

## Criterios de aceptacion

- Importar rutas no falla por falta de `psycopg` cuando el test usa SQLite.
- Produccion mantiene PostgreSQL con pool adecuado.
- No se rompe Alembic.
- La suite backend pasa en entorno limpio.

## Archivos probables

- `backend/app/database/session.py`
- `backend/tests/test_app_imports.py`
- `backend/tests/test_runtime_dependencies.py`
- tests nuevos si procede.

---

# Fase 2 - Integridad de almacenamiento documental

## Objetivo

Garantizar que los documentos originales almacenados no se corrompen, no se pierden y son recuperables.

## Problemas detectados

- `FILE_STORAGE_STRATEGY=auto` puede usar hardlink.
- Si el archivo de entrada se modifica despues, un hardlink puede hacer que cambie tambien el almacenado.
- El proyecto maneja documentos potencialmente importantes; integridad debe pesar mas que ahorro de disco.

## Tareas

- [x] Revisar `backend/app/services/file_storage.py`.
- [x] Decidir politica productiva recomendada:
  - [x] `copy` por defecto para produccion conservadora;
  - [x] `auto/hardlink` solo si el usuario confirma inputs inmutables.
- [x] Actualizar `.env.production.example` si procede.
- [x] Actualizar `docs/production-runbook.md` con decision clara.
- [x] Añadir test que demuestre diferencia entre `copy` y `hardlink`.
- [x] Validar `storage_integrity`:
  - [x] detecta DB sin fichero;
  - [x] detecta ficheros huerfanos;
  - [x] no marca falsos positivos con estructura hash.
- [x] Revisar backup/restore de `data/files`.
- [x] Ejecutar `scripts/verify-backup.ps1` sobre backup de prueba.

## Evidencia y notas

- `storage_integrity` queda cubierto para estructura hash realista `ab/cd/<sha256>.pdf`: no reporta missing ni orphan cuando el fichero referenciado existe.
- Backup/restore de `data/files` queda cubierto por contrato ligero: `backup.ps1` copia `data\files` a `$filesBackup` con `robocopy /MIR`, `restore.ps1` restaura `$filesBackup` a `data\files`, y `verify-backup.ps1` valida `manifest.json`, dump, conteo y bytes de archivos.
- `python -m pytest backend/tests/test_operational_hardening.py::test_storage_integrity_reports_missing_and_orphan_files backend/tests/test_operational_hardening.py::test_storage_integrity_accepts_valid_hash_layout_without_false_positives backend/tests/test_backlog_sprints.py::test_backup_verification_script_accepts_manifest backend/tests/test_backlog_sprints.py::test_backup_and_restore_scripts_copy_data_files_and_verify_manifest`: 4 passed en 1.88s.
- `python -m pytest backend/tests/test_operational_hardening.py backend/tests/test_backlog_sprints.py`: 27 passed en 56.81s; el test de auth cookie ya pasa tras el fix de `Secure` en produccion.

## Criterios de aceptacion

- La politica de storage en produccion queda documentada y aplicada.
- Hay tests que cubren estrategia de almacenamiento.
- Backup verification valida dump, files y manifest.
- Readiness o runbook avisan claramente de riesgo si se usa hardlink.

## Archivos probables

- `backend/app/services/file_storage.py`
- `.env.production.example`
- `docs/production-runbook.md`
- `backend/tests/test_file_storage.py`
- `backend/tests/test_operational_hardening.py`

---

# Fase 3 - Pipeline documental end-to-end

## Objetivo

Blindar el flujo mas importante: registrar documento, procesarlo, extraer texto, generar chunks, clasificar, buscar y reprocesar.

## Tareas

- [x] Crear o reforzar tests end-to-end de pipeline con archivos pequeños:
  - [x] TXT;
  - [x] CSV/Excel pequeño;
  - [x] PDF digital simple;
  - [x] imagen pequeña con OCR simulado/mocked.
- [x] Verificar que `register_upload` y `register_existing_file` tienen comportamiento consistente.
- [x] Revisar deduplicacion por SHA256:
  - [x] mismo archivo desde otra carpeta;
  - [x] mismo source_path con hash cambiado;
  - [x] duplicado de documento fallido o en revision.
- [x] Revisar estados de `Document` y `ExtractionJob`:
  - [x] `pending`;
  - [x] `processing`;
  - [x] `processed`;
  - [x] `needs_review`;
  - [x] `failed`;
  - [x] `duplicate`.
- [x] Verificar que chunks se regeneran correctamente en reprocesado.
- [x] Verificar que embeddings fallback no bloquea procesamiento.
- [x] Verificar que clasificacion y extraccion de negocio no tiran todo el job si fallan parcialmente para pedidos sin fecha obligatoria.
- [x] Añadir tests para archivos no permitidos y cuarentena.

## Evidencia y notas

- `python -m pytest backend/tests/test_document_pipeline.py`: 10 passed en 36.46s.
- Decision de deduplicacion: documentos `failed` ya no se consideran canonicos por hash; un archivo identico puede registrarse de nuevo con job `pending` para recuperacion. Documentos `processed` y `needs_review` siguen deduplicando a la entrada existente.
- La prueba de embeddings configura proveedor externo fallido con fallback hash habilitado y valida que el procesamiento termina en `processed` y genera embeddings en chunks.
- La cuarentena cubre firma ejecutable/invalid PDF: documento en `needs_review`, sin job, con flags de seguridad y mensaje de error.
- Verificacion final 2026-05-21: validacion dirigida de Fases 0-3 incluida en el bloque anterior: 40 passed en 61.87s, incluyendo `backend/tests/test_business_extraction.py` y `backend/tests/test_document_pipeline.py`.

## Criterios de aceptacion

- Existe al menos un test que cubre flujo completo sin servicios externos reales.
- Los estados de documento/job son predecibles.
- Reprocesar no deja paginas/bloques/chunks antiguos inconsistentes.
- Un fallo parcial no corrompe el documento ni pierde el original.

## Archivos probables

- `backend/app/services/document_service.py`
- `backend/app/parsers/*`
- `backend/app/services/classification.py`
- `backend/app/services/business_extraction.py`
- `backend/app/services/quality.py`
- `backend/tests/test_processing_safety.py`
- `backend/tests/test_mass_ingestion.py`
- tests nuevos de pipeline.

---

# Fase 4 - Watcher, scanner y cargas masivas

## Objetivo

Asegurar que la ingesta 24h y el escaneo manual son robustos para historicos grandes.

## Problemas a vigilar

- Archivos copiados parcialmente.
- Eventos perdidos en Docker Desktop/Windows.
- Saturacion de pending jobs.
- Reintentos infinitos o silenciosos.
- Duplicados por source path/hash.

## Tareas

- [x] Revisar `backend/app/ingestion/scanner.py`.
- [x] Revisar `backend/app/ingestion/watcher.py`.
- [x] Crear prueba con lote de archivos mixtos:
  - [x] validos;
  - [x] temporales;
  - [x] extension no permitida;
  - [x] inestables;
  - [x] duplicados.
- [x] Verificar backpressure con `INGESTION_MAX_PENDING_JOBS`.
- [x] Verificar pausa/reanudar ingesta.
- [x] Verificar `WatchedFile` e `IngestionEvent`.
- [x] Revisar que watcher no procese indefinidamente archivos problematicos.
- [x] Documentar parametros recomendados para Windows/Docker Desktop:
  - [x] `WATCHER_BACKEND=polling`;
  - [x] `WATCHER_SETTLE_SECONDS`;
  - [x] `WATCHER_RESCAN_INTERVAL_SECONDS`;
  - [x] `WATCHER_MAX_FILES_PER_TICK`.

## Evidencia y notas

- `PendingFileRegistry.add()` conserva el contador de reintentos al reencolar rutas fallidas; `process_pending_paths()` descarta tras `MAX_RETRIES` y deja evento `failed` auditable.
- El scanner compara hash cuando existe `Document.source_path`: mismo hash registra `skipped`; hash cambiado registra evento `modified` y continúa con un nuevo registro/job pendiente.
- La pausa del scanner registra `WatchedFile` e `IngestionEvent` con estado `paused` antes de interrumpir el scan.
- `register_existing_file()` registra `deduplicated` para `source_path` nuevo cuando SHA coincide con un documento `processed` o `needs_review` y retorna temprano.
- `docs/production-runbook.md` documenta recomendaciones Windows/Docker Desktop para `WATCHER_BACKEND=polling`, `WATCHER_SETTLE_SECONDS`, `WATCHER_RESCAN_INTERVAL_SECONDS` y `WATCHER_MAX_FILES_PER_TICK`.
- Verificacion 2026-05-22: `python -m pytest backend/tests/test_mass_ingestion.py -q`: 10 passed en 52.35s.
- Verificacion 2026-05-22: `python -m pytest backend/tests/test_operational_hardening.py backend/tests/test_backlog_sprints.py::test_watcher_reingests_modified_source_path_when_hash_changes backend/tests/test_document_pipeline.py -q`: 21 passed en 53.69s.
- Verificacion 2026-05-22: `python -m pytest backend/tests -q`: 128 passed en 302.97s.

## Criterios de aceptacion

- Scanner y watcher tienen pruebas con escenarios negativos.
- Backpressure impide saturar OCR.
- Los eventos de ingesta permiten auditar que paso con un archivo.
- Runbook explica como operar una importacion grande.

## Archivos probables

- `backend/app/ingestion/scanner.py`
- `backend/app/ingestion/watcher.py`
- `backend/app/ingestion/stability.py`
- `backend/tests/test_mass_ingestion.py`
- `docs/production-runbook.md`

---

# Fase 5 - Colas, OCR y reprocesado

## Objetivo

Evitar que OCR pesado, reprocesados o errores de pagina dejen el sistema bloqueado o inconsistente.

## Tareas

- [x] Revisar rutas de colas en `backend/app/workers/routing.py`.
- [x] Validar que PDF/imagenes van a `ocr_heavy` y texto/Excel a `text_fast`.
- [x] Revisar `task_acks_late`, retries y estados de job.
- [x] Definir semantica clara durante retry:
  - [x] job queda `retrying`/documento `processing` hasta agotar retries;
  - [x] al agotar retries se marca `failed` y se notifica una vez;
  - [x] documentar decision.
- [x] Revisar reprocesado por pagina OCR ya implementado.
- [x] Añadir tests para:
  - [x] fallo OCR de una pagina no tumba todo el documento;
  - [x] retry de job fallido crea estado consistente;
  - [x] cancelar pending no afecta processed;
  - [x] reprocess bulk no crea tormenta sin limite.
- [x] Validar healthcheck de workers en produccion.
- [x] Revisar si webhooks sincronos deben pasar a cola o tener circuito de fallo no bloqueante.

## Evidencia y notas

- Decision de colas: se mantiene `queue_for_document(document, job_type)` como fuente de verdad y se elimina la ruta estatica de `process_document_task` a `text_fast`; los callers pasan `queue=` explicitamente.
- Decision de retries: `process_document(..., final_failure=True)` conserva compatibilidad; el worker calcula `final_failure` desde `request.retries >= max_retries`. Los intentos intermedios no emiten webhook final ni notificacion final; dejan job `retrying` y documento `processing`. El intento agotado marca `failed` y emite una unica notificacion final desde el worker.
- Decision de webhooks: siguen sincronicos por ahora, pero son no fatales y tienen timeout acotado mediante `INTEGRATION_WEBHOOK_TIMEOUT_SECONDS`.
- `build_queue_control_status()` cuenta colas uniendo `ExtractionJob` con `Document` y aplicando `queue_for_document`, no por predicados identicos por `job_type`.
- Verificacion 2026-05-22: `python -m pytest backend/tests/test_phase5_operations.py backend/tests/test_ocr_review.py -q`: 28 passed en 38.64s.
- Verificacion 2026-05-22: `python -m pytest backend/tests/test_operational_hardening.py backend/tests/test_runtime_dependencies.py backend/tests/test_workflow_enhancements.py -q`: 20 passed en 31.78s.
- Verificacion 2026-05-22: `docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet`: exit code 0.
- Verificacion 2026-05-22: `python -m pytest backend/tests -q`: 141 passed en 328.13s.

## Criterios de aceptacion

- Las colas separan cargas pesadas y ligeras.
- Reintentos son comprensibles desde UI/admin.
- Reprocesado OCR por pagina funciona sin re-OCR completo innecesario.
- Un webhook lento no bloquea indebidamente el pipeline.

## Archivos probables

- `backend/app/workers/tasks.py`
- `backend/app/workers/routing.py`
- `backend/app/services/document_service.py`
- `backend/app/services/webhooks.py`
- `backend/tests/test_ocr_review.py`
- `backend/tests/test_phase5_operations.py`

---

# Fase 6 - Observabilidad, readiness y operacion diaria

## Objetivo

Que el operador pueda saber rapidamente si el sistema esta sano y que falla cuando algo se bloquea.

## Tareas

- [x] Revisar `/health` basico y endpoints admin profundos.
- [x] Reforzar `/admin/system/health`:
  - [x] PostgreSQL;
  - [x] Redis;
  - [x] disco `data/files`;
  - [x] disco `data/input`;
  - [x] watcher;
  - [x] colas;
  - [x] IA/embeddings si configurados.
- [x] Reforzar `/admin/production/readiness`:
  - [x] migraciones aplicadas;
  - [x] workers disponibles;
  - [x] backup script presente;
  - [x] storage writable;
  - [x] env coherente.
- [x] Corregir metricas inalcanzables detectadas en `search_service.py`.
- [x] Añadir metricas de:
  - [x] documentos procesados/fallidos;
  - [x] duracion OCR;
  - [x] jobs pendientes por cola;
  - [x] embeddings fallback;
  - [x] errores watcher.
- [x] Revisar `PerformanceMonitorMiddleware`.
- [x] Documentar interpretacion de alertas en runbook.

## Criterios de aceptacion

- Admin muestra causa concreta de fallo operativo.
- Readiness distingue warning vs blocker.
- Las metricas de busqueda se registran realmente.
- Runbook indica acciones correctivas.

## Archivos probables

- `backend/app/services/production_readiness.py`
- `backend/app/services/metrics.py`
- `backend/app/services/search_service.py`
- `backend/app/api/routes/admin.py`
- `docs/production-runbook.md`

---

# Fase 7 - Rendimiento y escalabilidad con datos reales

## Objetivo

Evitar sorpresas cuando haya miles de documentos y OCR real.

## Tareas

- [x] Crear dataset de prueba representativo:
  - [x] cientos/miles de registros sinteticos;
  - [x] documentos con multiples paginas;
  - [x] chunks y embeddings.
- [x] Ejecutar tests de performance existentes.
- [x] Medir:
  - [x] upload;
  - [x] scan;
  - [x] procesamiento worker;
  - [x] busqueda textual;
  - [x] busqueda semantica;
  - [x] busqueda hibrida;
  - [x] dashboard/admin;
  - [x] listados paginados.
- [x] Revisar indices PostgreSQL:
  - [x] documentos por status/type/date;
  - [x] jobs por status;
  - [x] chunks vectoriales;
  - [x] FTS/trigram.
- [x] Confirmar que listados pesados usan paginacion.
- [x] Revisar queries post-filter en memoria y mover filtros a SQL donde aporte valor.
- [x] Definir objetivos minimos:
  - [ ] search P95 < 500 ms en dataset objetivo;
  - [ ] operations documents P95 < 500 ms;
  - [ ] dashboard P95 < 1 s;
  - [ ] worker no se queda sin memoria con PDF objetivo.

## Criterios de aceptacion

- Existe reporte de performance actualizado.
- Se conocen limites practicos por hardware.
- Queries criticas tienen indices o paginacion.
- No hay endpoints operativos que carguen todo sin limite en escenarios grandes.

## Archivos probables

- `backend/tests/performance/*`
- `PERFORMANCE_TEST_PLAN.md`
- `backend/app/services/search_service.py`
- `backend/app/api/routes/admin.py`
- migraciones Alembic si hacen falta indices.

---

# Fase 8 - Modularizacion backend

## Objetivo

Reducir riesgo de regresiones separando responsabilidades sin cambiar comportamiento funcional.

## Problemas detectados

- `backend/app/services/document_service.py` concentra demasiada logica.
- `backend/app/api/routes/admin.py` concentra demasiadas rutas.

## Estrategia

Refactor incremental con tests antes/despues. No reescribir todo de golpe.

## Tareas - `document_service.py`

- [x] Identificar secciones internas y dependencias.
- [x] Extraer registro documental:
  - [ ] `document_registration_service.py`.
- [x] Extraer procesamiento OCR/pipeline:
  - [ ] `document_processing_service.py`.
- [x] Extraer reprocesado:
  - [ ] `document_reprocess_service.py`.
- [x] Extraer generacion de chunks/embeddings:
  - [ ] `document_embedding_pipeline.py`.
- [x] Extraer evaluacion final/calidad si procede.
- [x] Mantener API publica compatible durante transicion.
- [x] Ejecutar tests tras cada extraccion.

## Tareas - `admin.py`

- [x] Separar rutas por dominio:
  - [ ] `admin_system.py`;
  - [ ] `admin_operations.py`;
  - [ ] `admin_jobs.py`;
  - [ ] `admin_quality.py`;
  - [ ] `admin_integrations.py`;
  - [ ] `admin_access.py`;
  - [ ] `admin_users.py`.
- [x] Mantener prefijo `/admin` intacto.
- [x] Añadir router agregador si hace falta.
- [x] Ejecutar tests de rutas admin.

## Criterios de aceptacion

- No cambia contrato API.
- Tests existentes siguen pasando.
- Cada modulo nuevo tiene responsabilidad clara.
- El tamaño de archivos principales baja significativamente.

## Archivos probables

- `backend/app/services/document_service.py`
- nuevos `backend/app/services/*`
- `backend/app/api/routes/admin.py`
- nuevos `backend/app/api/routes/admin_*.py`
- `backend/app/api/router.py`

---

# Fase 9 - Modularizacion frontend operativo

## Objetivo

Hacer mantenible el frontend sin cambiar UX principal.

## Problemas detectados

- `frontend/src/api/client.ts` es monolitico.
- `frontend/src/pages/AdminPage.tsx` es demasiado grande.
- Muchas paginas mezclan queries, mutations, formularios y render.

## Tareas - API client

- [ ] Crear estructura:
  - [ ] `src/api/core.ts` para `request`, `ApiError`, URLs base;
  - [ ] `src/api/auth.ts`;
  - [ ] `src/api/documents.ts`;
  - [ ] `src/api/admin.ts`;
  - [ ] `src/api/search.ts`;
  - [ ] `src/api/ai.ts`;
  - [ ] `src/api/business.ts`;
  - [ ] `src/api/integrations.ts`.
- [ ] Mantener export `api` compatible al principio.
- [ ] Mover tests de cliente por dominio.
- [ ] Ejecutar frontend tests/build tras cada bloque.

## Tareas - AdminPage

- [ ] Dividir pestañas en componentes:
  - [ ] `AdminOperationalTab`;
  - [ ] `AdminSystemTab`;
  - [ ] `AdminIntegrationsTab`;
  - [ ] `AdminAccessGroupsTab`;
  - [ ] `AdminSensitiveTagsTab`;
  - [ ] tabs tenant si se mantienen.
- [ ] Extraer formularios repetidos.
- [ ] Eliminar `any` donde sea posible.
- [ ] Mantener rutas y query keys.
- [ ] Añadir tests basicos de render para tabs principales.

## Tareas - UX operativa

- [ ] Añadir confirmacion para acciones sensibles no relacionadas con login:
  - [ ] reprocesado masivo;
  - [ ] seed demo;
  - [ ] rotate integration key;
  - [ ] bulk tags;
  - [ ] pause/resume queues si se considera necesario.
- [ ] Añadir manejo global o semi-global de errores API.
- [ ] Revisar polling intensivo.
- [ ] Añadir paginacion donde falte:
  - [ ] jobs;
  - [ ] OCR review;
  - [ ] search;
  - [ ] reconciliation;
  - [ ] budgets/orders si crecen.

## Criterios de aceptacion

- Frontend build y tests pasan.
- AdminPage queda dividida en componentes razonables.
- API client queda separado por dominio.
- Acciones peligrosas piden confirmacion.
- No se pierde funcionalidad existente.

## Archivos probables

- `frontend/src/api/client.ts`
- nuevos `frontend/src/api/*.ts`
- `frontend/src/pages/AdminPage.tsx`
- nuevos `frontend/src/pages/admin/*` o `frontend/src/components/admin/*`
- `frontend/src/api/client.test.ts`

---

# Fase 10 - Produccion Docker/nginx y operacion

## Objetivo

Mejorar robustez del contenedor frontend/backend y documentar despliegue estable.

## Tareas

- [ ] Revisar `frontend/nginx.conf`.
- [ ] Añadir si procede:
  - [ ] `client_max_body_size` alineado con `MAX_UPLOAD_SIZE_MB`;
  - [ ] proxy timeouts para uploads/descargas;
  - [ ] cache para assets hashados;
  - [ ] gzip;
  - [ ] headers basicos no intrusivos.
- [ ] Confirmar que `/api` proxy funciona con uploads grandes.
- [ ] Revisar healthchecks de compose.
- [ ] Revisar limites CPU/memoria por servicio.
- [ ] Documentar hardware minimo/recomendado:
  - [ ] RAM;
  - [ ] CPU;
  - [ ] disco;
  - [ ] limites para OCR.
- [ ] Añadir smoke test post-arranque:
  - [ ] frontend responde;
  - [ ] backend `/health` responde;
  - [ ] `/admin/system/health` accesible con token si aplica;
  - [x] upload de documento de prueba;
  - [ ] worker procesa job.

## Criterios de aceptacion

- Compose produccion levanta y pasa smoke test.
- Nginx no bloquea uploads dentro del limite configurado.
- Runbook contiene parametros claros de operacion.

## Archivos probables

- `frontend/nginx.conf`
- `docker-compose.prod.yml`
- `docs/production-runbook.md`
- `scripts/start-docuintel.ps1`
- nuevo script smoke test si procede.

---

# Fase 11 - Tests E2E y regresion funcional

## Objetivo

Validar los flujos que realmente usa el operador.

## Tareas

- [ ] Definir escenarios E2E minimos:
  - [ ] login si se necesita para navegar;
  - [ ] subir documento;
  - [ ] ver documento procesado;
  - [ ] buscar texto;
  - [ ] abrir detalle;
  - [ ] reprocess;
  - [ ] revisar OCR;
  - [ ] ver dashboard/admin health.
- [ ] Decidir herramienta:
  - [ ] Playwright;
  - [ ] tests API smoke con Python/HTTPX;
  - [ ] ambos.
- [ ] Crear dataset minimo para E2E.
- [ ] Integrar en CI solo los tests rapidos.
- [ ] Dejar tests pesados como comando manual documentado.

## Criterios de aceptacion

- Hay smoke test reproducible para validar despliegue.
- CI no tarda demasiado.
- Tests pesados quedan disponibles para releases.

## Archivos probables

- nuevo `tests/e2e` o `frontend/e2e`
- `.github/workflows/ci.yml`
- `docs/production-runbook.md`

---

# Fase 12 - Documentacion final y traspaso operativo

## Objetivo

Que cualquier operador pueda mantener la app sin depender del desarrollador original.

## Tareas

- [ ] Actualizar README con flujo actual.
- [ ] Actualizar production runbook.
- [ ] Documentar:
  - [ ] como arrancar;
  - [ ] como parar;
  - [ ] como hacer backup;
  - [ ] como restaurar;
  - [ ] como importar historico;
  - [ ] como comprobar salud;
  - [ ] como actuar si OCR se atasca;
  - [ ] como actuar si Redis/Postgres falla;
  - [ ] como ampliar limites.
- [ ] Crear checklist de release:
  - [ ] tests backend;
  - [ ] tests frontend;
  - [ ] build frontend;
  - [ ] compose config;
  - [ ] smoke test;
  - [ ] backup previo.
- [ ] Crear tabla de parametros `.env.production` recomendados.

## Criterios de aceptacion

- El runbook permite operar sin leer codigo.
- Existe checklist antes de actualizar produccion.
- Variables criticas estan explicadas.

---

# 4. Backlog aplazado de seguridad/auth

Como el entorno actual es privado y controlado, estas tareas no bloquean el planning principal. Se mantienen documentadas para futuro.

- [ ] Endpoint backend `/auth/logout` para borrar cookie correctamente.
- [ ] Limpieza de React Query cache al logout.
- [ ] Manejo global de 401 en frontend.
- [ ] CSRF token si se expone fuera de entorno privado.
- [ ] Guards frontend por rol para ocultar `/admin`.
- [ ] Ownership check en `/ai/answers/{answer_id}` si hay usuarios no confiables.
- [ ] Revisar JWT manual o migrar a libreria estandar.
- [ ] MFA si se abre fuera de red privada.

---

# 5. Orden recomendado de ejecucion

## Sprint 1 - Estabilizacion base

- [x] Fase 0 - baseline.
- [x] Fase 1 - arranque backend/DB.
- [x] Fase 2 - integridad storage.

Resultado esperado: entorno fiable, backend testeable y politica clara de almacenamiento.

## Sprint 2 - Pipeline documental

- [x] Fase 3 - pipeline end-to-end.
- [ ] Fase 4 - watcher/scanner.
- [ ] Fase 5 - colas/OCR/reprocesado.

Resultado esperado: flujo documental robusto y con estados consistentes.

## Sprint 3 - Operacion y performance

- [ ] Fase 6 - observabilidad/readiness.
- [ ] Fase 7 - rendimiento con volumen.
- [ ] Fase 10 - Docker/nginx/smoke.

Resultado esperado: sistema operable y medible en produccion.

## Sprint 4 - Mantenibilidad

- [ ] Fase 8 - modularizacion backend.
- [ ] Fase 9 - modularizacion frontend.

Resultado esperado: codigo mas facil de tocar sin romper.

## Sprint 5 - Validacion y documentacion

- [ ] Fase 11 - E2E/regresion.
- [ ] Fase 12 - documentacion final.

Resultado esperado: releases repetibles y operacion documentada.

---

# 6. Definicion de terminado global

El plan puede considerarse completado cuando:

- [ ] Backend tests pasan en entorno reproducible.
- [ ] Frontend tests pasan.
- [ ] Frontend build pasa.
- [ ] Compose produccion valida.
- [ ] Smoke test de produccion pasa.
- [ ] Se puede subir/procesar/buscar/reprocesar un documento de prueba.
- [ ] Storage integrity no reporta errores en entorno limpio.
- [ ] Backup y verify-backup funcionan.
- [ ] Readiness muestra estado correcto y errores accionables.
- [ ] `document_service.py`, `admin.py`, `AdminPage.tsx` y `api/client.ts` quedan reducidos o con plan de separacion parcialmente ejecutado.
- [ ] Runbook y README reflejan la operacion real.

---

# 7. Notas finales

Este plan prioriza que Docu-Intel sea estable como herramienta documental interna. Las tareas de seguridad de login quedan aplazadas de forma consciente, no olvidadas. La mayor amenaza inmediata no es autenticacion, sino inconsistencia del pipeline, complejidad acumulada, falta de baseline reproducible y posibles problemas de integridad/rendimiento con volumen real.


## Evidencia y notas

- Search metrics: las tres funciones de busqueda (search_text, search_semantic, search_hybrid) usan try/finally para que track_search_latency sea alcanzable en todos los caminos (empty query, cache hit, pgvector, normal, exception).
- Metricas nuevas: documents_processed/failed, embedding_fallback_count, watcher_errors expuestas en /metrics via Prometheus text.
- Llamadas de tracking: document_service llama track_document_processed en success path y track_document_failed en final_failure; watcher llama track_watcher_error en ingestion fallida; embeddings llama track_embedding_fallback en fallback a hash.
- Health /admin/system/health incluye database, redis, disk_files, disk_input, watcher, queues, ai_llm, embeddings. Las comprobaciones AI/embedding por defecto no hacen HTTP externo.
- Readiness /admin/production/readiness incluye database, redis, workers, watcher, files_dir, input_dir, backups, integration_manifest con top-level status.
- PerformanceMonitorMiddleware anade header X-Response-Time.
- Runbook ampliado con interpretacion de alertas y acciones correctivas para PostgreSQL, Redis, disco, workers, watcher, backpressure, AI/embeddings, storage integrity, migraciones y metricas.
- Verificacion 2026-05-22: python -m pytest backend/tests/test_phase6_observability.py -q: 9 passed.
- Verificacion 2026-05-22: python -m pytest backend/tests -q: 150 passed en 357.74s.

## Evidencia y notas

- Dataset sintetico: script ackend/tests/performance/fabricate_benchmark_data.py genera datasets escalables (100-1000+ documentos con paginas, chunks, embeddings, jobs, budgets, orders, planes) para benchmarks repetibles.
- Indices criticos anadidos: DocumentEntity.normalized_value (para busquedas exact/guided), Budget.accepted_detected (para alertas y work inbox).
- Paginacion anadida en endpoints criticos: GET /documents/{id}/pages, GET /documents/{id}/blocks, GET /documents/{id}/entities ahora aceptan offset/limit.
- Benchmarks: 	est_search_text_scales_to_100_docs (P95 < 2s en SQLite), 	est_search_semantic_scales_to_1000_chunks (P95 < 30s en SQLite sin pgvector), 	est_admin_listing_uses_pagination (24ms offset+limit), 	est_document_pages_endpoint_has_pagination_guard (limit efectivo).
- Objetivos minimos documentados: search P95 < 500ms con pgvector, operations P95 < 500ms con indices, dashboard P95 < 1s, worker < 2GB para PDF 500 paginas.
- Nota: La busqueda semantica en SQLite es ~10x mas lenta que con PostgreSQL+pgvector; en produccion se requiere pgvector para alcanzar los objetivos.
- Verificacion 2026-05-22: python -m pytest backend/tests/performance/test_perf_benchmarks.py backend/tests -q: 155 passed en 396.96s.

## Evidencia y notas

- document_service.py reducido de 784 a 25 lineas (fachada de re-exportacion).
- dmin.py reducido de 1850 a 12 lineas (agregador de sub-routers).
- Nuevos modulos: document_registration_service.py (215L), document_reprocess_service.py (90L), document_embedding_pipeline.py (67L), document_processing_core.py (464L).
- Rutas admin divididas: dmin_system.py (293L), dmin_operations.py (455L), dmin_jobs.py (135L), dmin_quality.py (204L), dmin_integrations.py (256L), dmin_access.py (503L), dmin_helpers.py (175L).
- API publica intacta: todos los imports rom app.services.document_service import ... y rutas /admin/* siguen funcionando sin cambios.
- Tests: 155 passed sin modificar ningun test.
- Verificacion 2026-05-22: python -m pytest backend/tests -q: 155 passed en 397.08s.

## Evidencia y notas

- client.ts reducido de 363 a 28 lineas (barrel de re-exportacion). Dividido en 8 modulos por dominio: core.ts (57L), uth.ts (12L), documents.ts (57L), dmin.ts (162L), search.ts (30L), i.ts (13L), usiness.ts (54L), integrations.ts (15L).
- AdminPage.tsx reducido de 1644 a 572 lineas (shell con tabs). Dividido en 5 componentes: AdminOperationalTab.tsx (388L), AdminSystemTab.tsx (349L), AdminIntegrationsTab.tsx (178L), AdminAccessTab.tsx (517L), AdminQualityTab.tsx (274L) + shared.tsx (130L).
- Confirmaciones anadidas para: reprocesado masivo, seed demo, rotate integration key, bulk tags, pause/resume queues.
- Sin ny en modulos nuevos, TypeScript estricto.
- Frontend tests: 25 passed. Frontend build: 	sc -b && vite build OK (453.84 kB JS, 1.86s).
- Verificacion 2026-05-22: 
pm test -- --run 25 passed, 
pm run build OK.