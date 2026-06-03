# Docu-Intel Production Runbook

Este runbook resume la operación diaria con Docker Compose en un PC Windows con Docker Desktop/WSL. No asume Coolify ni despliegue Linux dedicado.

## Arranque

1. Copiar `.env.production.example` a `.env.production`.
2. Cambiar todos los secretos: `POSTGRES_PASSWORD`, `DATABASE_URL`, `JWT_SECRET`, `ADMIN_PASSWORD` e integration keys.
3. Ajustar `CORS_ORIGINS` al dominio real.
4. Ajustar `AI_BASE_URL`, `AI_MODEL` y `EMBEDDING_*` al servidor local.
5. Crear carpetas:

```powershell
mkdir data\files
mkdir data\input
```

6. Levantar:

```powershell
$env:DOCUINTEL_ENV_FILE=".env.production"
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

O usa el script de arranque:

```powershell
.\scripts\start-docuintel.ps1 -EnvFile .env.production
```

El frontend queda expuesto por `FRONTEND_PORT`, por defecto `8080`. PostgreSQL y Redis no publican puertos.

## Ingesta Masiva

- Copiar documentos a `data/input/presupuestos`, `pedidos`, `facturas`, `planos`, `imagenes` u `otros`.
- El watcher espera a que los archivos estén estables antes de registrarlos.
- `INGESTION_MAX_PENDING_JOBS` limita la presión sobre OCR y CPU.
- Desde Administración se puede pausar o reanudar la ingesta.
- En Windows con Docker Desktop se recomienda `WATCHER_BACKEND=polling` para evitar eventos perdidos del watcher nativo sobre volúmenes montados.
- Ajustes recomendados para cargas grandes en Windows/Docker Desktop: `WATCHER_SETTLE_SECONDS=10` a `30` según tamaño de archivo, `WATCHER_RESCAN_INTERVAL_SECONDS=300` a `900` para reconciliar eventos perdidos y `WATCHER_MAX_FILES_PER_TICK=10` a `50` según CPU/OCR disponible.
- Si se copian archivos muy grandes o desde red, subir `WATCHER_SETTLE_SECONDS` y mantener `INGESTION_MAX_PENDING_JOBS` conservador evita registrar archivos incompletos y saturar workers.

Para importar un histórico grande sin navegador:

```powershell
.\scripts\import_initial.ps1 -SourceDir D:\historico_docuintel -DestinationDir data\input
.\scripts\check_import_integrity.ps1 -SourceDir D:\historico_docuintel -DestinationDir data\input
```

Para sincronizaciones posteriores sin borrar origen:

```powershell
.\scripts\sync_incremental.ps1 -SourceDir D:\historico_docuintel -DestinationDir data\input
```

## Backups

Opcion recomendada en Windows/PowerShell:

```powershell
.\scripts\backup.ps1 -EnvFile .env.production
.\scripts\verify-backup.ps1 -BackupDir backups\YYYYMMDD_HHMMSS
.\scripts\restore.ps1 -BackupDir backups\YYYYMMDD_HHMMSS -EnvFile .env.production
```

El backup guarda PostgreSQL y `data\files`, genera `manifest.json`, rota backups antiguos y falla si el dump pesa menos de lo esperado. `verify-backup.ps1` comprueba que el dump, los archivos y el manifest coinciden antes de usar el backup. Prueba el restore en una instancia separada antes de cargar documentacion real.

Backup PostgreSQL:

```powershell
docker compose -f docker-compose.prod.yml exec -T postgres pg_dump -U app -d docuintel -Fc > backups\docuintel.dump
```

Backup de originales:

```powershell
robocopy data\files backups\files /MIR
```

Restore PostgreSQL en una base vacía:

```powershell
docker compose -f docker-compose.prod.yml exec -T postgres pg_restore -U app -d docuintel --clean --if-exists < backups\docuintel.dump
```

Restore de originales:

```powershell
robocopy backups\files data\files /MIR
```

## Operación

- `GET /admin/system/health`: salud de PostgreSQL, Redis, disco, watcher y colas.
- `GET /admin/production/readiness`: readiness productivo estricto para validar DB, Redis, workers, watcher, directorios, backup y manifest de integración.
- `GET /admin/operations/overview`: centro de operaciones con ETA, volumen, OCR bajo, calidad documental y fuentes recientes.
- `GET /admin/operations/documents`: listado operativo paginado para grandes volúmenes.
- `GET /admin/queues`: estado de ingesta y colas.
- `POST /admin/queues/pause`: pausa watcher/scan.
- `POST /admin/queues/resume`: reanuda watcher/scan.
- `POST /admin/jobs/{id}/retry`: crea un nuevo job para el documento.
- `POST /admin/jobs/{id}/cancel`: cancela jobs pendientes o fallidos.
- `GET /admin/audit-logs/export/json` y `/csv`: exportación de auditoría.
- `GET /admin/quality/ocr-review`: bandeja de OCR bajo con preview, bloques, notas, aprobación y denegación.
- `GET /admin/quality/summary`: resumen de reglas de calidad y documentos afectados.
- `POST /admin/quality/recalculate`: recalcula calidad documental por lotes acotados.
- `POST /admin/quality/pages/{page_id}/reprocess-ocr`: reencola OCR del documento de la página seleccionada.
- `GET /admin/security/tags` y `POST /admin/security/tags`: catálogo de tags sensibles.
- `POST /admin/documents/bulk-tags`: añade o quita tags sensibles a documentos en lote.
- `GET /admin/access/effective`: muestra permisos efectivos, tipos documentales, tags bloqueados y campos redactados.
- `GET /admin/storage/integrity`: detecta registros sin fichero físico y ficheros huérfanos en `/data/files`.
- En produccion se recomienda `FILE_STORAGE_STRATEGY=copy` para evitar que un hardlink comparta cambios con el archivo de entrada si la carpeta origen no es inmutable.

## Integración IA Externa

- Crear clientes API desde Administración, pestaña Integraciones.
- Guardar la API key generada porque solo se muestra una vez.
- La IA externa debe llamar `GET /integrations/v1/manifest`.
- Las tools se ejecutan en `POST /integrations/v1/tools/execute`.
- En `tools/execute`, `sandbox=true` sirve para validar scope, fuentes y redacciones sin tratarlo como respuesta final.
- Docu-Intel aplica redacción y auditoría antes de devolver contexto.
- `POST /integrations/v1/webhooks/test` permite comprobar el webhook configurado.

## Notas De Configuración

- Hoteles/cadenas quedan ocultos por defecto con `VITE_ENABLE_TENANT_ADMIN=false`.
- La revisión OCR versionada, timeline documental, tareas persistentes, conciliación, búsquedas guardadas, reglas de notificación y mediciones manuales de planos ya tienen endpoints y pantallas base.

## Interpretación de alertas y acciones correctivas

### PostgreSQL no disponible
- **Health/readiness**: `database: error`
- **Causa probable**: contenedor postgres parado, sin RAM, volumen corrupto o mal configurado.
- **Acción**: `docker compose -f docker-compose.prod.yml ps postgres`, ver logs con `docker compose logs postgres`. Si no arranca, restaurar desde backup.

### Redis no disponible
- **Health/readiness**: `redis: warning`
- **Causa probable**: contenedor redis parado, sin RAM, o `redis_url` mal configurado.
- **Acción**: verificar `docker compose ps redis`. Sin Redis, la caché y el control de ingesta caen a memoria local; workers y colas Celery sí requieren Redis operativo.

### Disco bajo o no escribible
- **Health**: `disk_files` o `disk_input` con `status: error` o `usage_pct > 90`.
- **Causa probable**: volumen lleno, permisos insuficientes, montaje desconectado.
- **Acción**: liberar espacio con `docker system prune -f` o ampliar disco. Verificar que las rutas existen y tienen permisos.

### Workers caídos
- **Readiness**: `workers: error` (sin workers respondiendo a `celery inspect ping`).
- **Causa probable**: worker no arrancó, Redis inaccesible, código con error de importación.
- **Acción**: `docker compose ps worker`, `docker compose ps ocr-worker`. Revisar logs con `docker compose logs worker`. Si no se recupera, revisar montaje de código y dependencias.

### Watcher sin actividad
- **Health**: `watcher` con `ultimo evento` muy antiguo o `sin eventos` en producción.
- **Causa probable**: watcher parado, `data/input` sin archivos nuevos, configuración `WATCHER_BACKEND` inadecuada.
- **Acción**: en Windows/Docker Desktop usar `WATCHER_BACKEND=polling`. Verificar `docker compose ps` y logs del backend.

### Backpressure activo
- **Queues**: `backpressure_active: true`.
- **Causa probable**: demasiados jobs `pending`/`processing`, OCR lento, workers insuficientes.
- **Acción**: pausar ingesta (`POST /admin/queues/pause`), cancelar jobs no críticos, aumentar `INGESTION_MAX_PENDING_JOBS` si el hardware lo permite, o escalar workers.

### AI/embeddings no disponible
- **Health**: `ai_llm` o `embeddings` con `status: error`.
- **Causa probable**: URL o API key mal configurada, servicio externo caído.
- **Acción**: si hay fallback a hash (`EMBEDDING_FALLBACK_TO_HASH=true`) las búsquedas semánticas pierden calidad pero el sistema sigue operativo. Verificar configuración en `.env.production`.

### Integridad de storage
- **Storage integrity**: `missing_files > 0` u `orphan_files > 0`.
- **Causa probable**: archivos borrados manualmente, copia incompleta, error de montaje.
- **Acción**: si hay huérfanos (`orphan_files`), revisar si son válidos y se pueden reasignar. Si faltan (`missing_files`), revisar backup o reprocesar desde `data/input`.

### Migraciones no aplicadas
- **Readiness**: `migrations: error` (revisión de alembic no coincide con head).
- **Causa probable**: código actualizado sin ejecutar migraciones.
- **Acción**: `docker compose exec backend alembic upgrade head`.

### Métricas anómalas
- **`/metrics`** expone contadores clave. Valores a vigilar:
  - `docuintel_documents_failed_total` subiendo: revisar logs de workers.
  - `docuintel_watcher_errors_total` subiendo: archivos problemáticos en `data/input`.
  - `docuintel_embedding_fallback_total` subiendo: el servicio de embeddings no responde.
  - `docuintel_ocr_duration_seconds_avg` > 30s: PDFs muy grandes o OCR sobrecargado.
  - `docuintel_search_latency_seconds_avg` > 1s: revisar índices PostgreSQL y volumen de chunks.