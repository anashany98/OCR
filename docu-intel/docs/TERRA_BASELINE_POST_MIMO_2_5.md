# Línea base post-MIMO 2.5

Fecha: 2026-07-11  
Rama: `fix/remediacion-auditoria-2026-07`  
Commit de partida: `1436601 feat(M25): ejecucion integral plan MIMO 2.5 — estabilizacion, jerarquia, chat, imagenes, permisos, E2E`

## Estado del árbol

El árbol contiene cambios locales previos, tanto versionados como sin seguimiento. No se han eliminado, reescrito ni añadido al índice durante esta línea base. `git diff --check` termina correctamente; Git informa solo de avisos CRLF para tres documentos raíz y `backend/app/parsers/dxf.py`.

Entre los cambios locales hay archivos que pertenecen a fases posteriores (`ai/*`, `api/routes/*`, `plans.py`, métricas, overlays y servicios aún sin seguimiento). Cualquier modificación posterior de esos ficheros requiere revisar primero su diff completo.

## Servicios y esquema

`docker compose ps` informa backend, PostgreSQL, Redis, frontend, watcher, scheduler y workers como activos; los servicios con healthcheck están saludables.

- Esquema de la base activa: `0052_image_analysis`.
- Conteos activos: `documents=10`, `projects=3`, `document_occurrences=0`, `document_budget_links=0`, `communication_threads=0`, `communication_messages=0`, `image_analyses=0`.
- `docker compose run --rm migrate` se ejecuta contra la base activa.
- Se reconstruyó la imagen `migrate` desde el árbol actual. Un PostgreSQL temporal con pgvector 16 aplicó todas las revisiones desde `0001_initial_schema` hasta `0052_image_analysis` correctamente. El contenedor temporal fue eliminado al terminar.

## Validación inicial

| Comando | Resultado | Evidencia |
|---|---|---|
| `python -m compileall -q backend/app` | Pasa | Finaliza sin salida ni errores. |
| `python -m pytest -q backend/tests/test_project_path_resolver.py` | Pasa | 17 pruebas en 0.05 s al aislar la ejecución. |
| `python -m pytest -q backend/tests/test_classification.py` | Falla | 17 pasan y 1 falla: la clasificación devuelve `plano_arquitectura` cuando el contrato público de la prueba espera `plano`. |
| `python -m pytest -q backend/tests/test_mass_ingestion.py` | Bloqueada | No termina en 49 s ni emite progreso con `-vv -s`. La inspección muestra que `scan_input_folders()` añade `source_corpus_dir` y recorre `rglob()`: es el defecto que debe resolverse en Fase 4, no se ha ocultado ampliando el timeout. |
| `npm --prefix frontend run build` | Pasa | Vite construye correctamente. |
| `npm --prefix frontend run test` | Falla | Vitest inicia las pruebas, pero termina con `Error: Worker exited unexpectedly` de Tinypool bajo Node 22.14.0 antes de producir cobertura. |

## Bloqueos iniciales que deben conservarse como regresiones

1. Compatibilidad de planos: conservar `Document.document_type == "plano"` y separar el subtipo, según Fase 10.
2. El escáner normal no puede recorrer el corpus fijo; el arreglo pertenece a Fase 4 y debe incluir límites, cursor y pruebas de reanudación.
3. La cobertura frontend necesita una ejecución estable de Vitest; no se reducirá el umbral ni se ocultará el error del worker.

## Límites de esta fase

No se ha ejecutado backfill real ni se ha escrito en el corpus `D:\\TEST2025\\2025`. La siguiente fase empieza por la fuga de permisos: búsqueda exacta y dossier deben filtrar por `access_scope` antes de recuperar cualquier dato.
