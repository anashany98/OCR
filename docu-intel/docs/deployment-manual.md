# Docu-Intel Deployment Manual

Manual completo para desplegar Docu-Intel en servidores propios, VPS, máquinas virtuales cloud, NAS con Docker, Portainer, Coolify u otros entornos que soporten Docker Compose.

Este manual asume despliegue con `docker-compose.prod.yml`, que es el perfil recomendado para staging y producción. El `docker-compose.yml` base queda para desarrollo local.

## 1. Arquitectura

Docu-Intel se despliega como un conjunto de contenedores:

- `frontend`: React compilado servido por Nginx. Expone HTTP al exterior.
- `backend`: FastAPI. Ejecuta migraciones Alembic al arrancar y sirve la API.
- `worker`: Celery para extracción de texto, embeddings, mantenimiento y trabajos rápidos.
- `ocr-worker`: Celery separado para OCR pesado.
- `watcher`: observa `data/input` y registra documentos nuevos.
- `postgres`: PostgreSQL 16 con `pgvector`.
- `redis`: broker/cache para Celery y operaciones internas.

Flujo de red recomendado:

```text
Usuario -> HTTPS reverse proxy -> frontend:Nginx -> /api -> backend:8000
backend/worker/watcher -> postgres/redis
watcher -> data/input
backend/worker -> data/files
```

En producción no publiques PostgreSQL ni Redis. El `frontend` es el único servicio que debe quedar accesible desde fuera, normalmente detrás de TLS.

## 2. Requisitos

### 2.1 Software

- Docker Engine 24+ o Docker Desktop reciente.
- Docker Compose v2 (`docker compose`, no `docker-compose` antiguo).
- Git o un método equivalente para subir el proyecto al servidor.
- PowerShell 7+ si vas a usar los scripts `scripts/backup.ps1` y `scripts/restore.ps1` en Windows.
- Un reverse proxy para HTTPS en producción: Caddy, Nginx Proxy Manager, Traefik, Coolify, Cloudflare Tunnel o Nginx.

### 2.2 Hardware mínimo

Para demo o piloto pequeño:

- CPU: 2 vCPU.
- RAM: 6 GB.
- Disco: 50 GB SSD.

Para producción pequeña/mediana:

- CPU: 4-8 vCPU.
- RAM: 16-32 GB.
- Disco: SSD/NVMe con espacio suficiente para originales, OCR, previews y backups.
- OCR worker: reserva 4 vCPU y 6 GB RAM si se procesan PDFs escaneados o imágenes grandes.

Regla de capacidad de disco:

```text
espacio útil >= documentos originales + crecimiento 12 meses + backups locales temporales
```

Si guardas 500 GB de documentos, planifica como mínimo 1.2-1.5 TB entre datos, crecimiento e instantáneas de backup.

### 2.3 Red y DNS

- Dominio o subdominio, por ejemplo `docuintel.empresa.com`.
- TLS válido.
- Puerto 80/443 abiertos en el reverse proxy.
- Si usas IA/embeddings locales fuera de Docker, el servidor debe poder alcanzar `AI_BASE_URL` y `EMBEDDING_BASE_URL`.

## 3. Estructura de datos persistentes

El despliegue usa estas rutas del host:

```text
docu-intel/
  data/
    input/    documentos entrantes vigilados por watcher
    files/    originales almacenados por hash y artefactos persistentes
  backups/    backups generados por scripts
```

PostgreSQL y Redis usan volúmenes Docker nombrados:

- `postgres_data`
- `redis_data`

No borres esos volúmenes salvo que quieras eliminar la instalación.

## 4. Variables de entorno

Copia la plantilla:

```bash
cp .env.production.example .env.production
```

En Windows PowerShell:

```powershell
Copy-Item .env.production.example .env.production
```

Edita obligatoriamente:

| Variable | Obligatoria | Descripción |
| --- | --- | --- |
| `ENVIRONMENT=production` | Sí | Activa validaciones estrictas de secretos. |
| `POSTGRES_PASSWORD` | Sí | Contraseña real de PostgreSQL. |
| `DATABASE_URL` | Sí | Debe usar la misma contraseña: `postgresql+psycopg://app:<pass>@postgres:5432/docuintel`. |
| `JWT_SECRET` | Sí | Token aleatorio largo, 64+ caracteres recomendado. |
| `ADMIN_EMAIL` | Sí | Usuario administrador inicial. |
| `ADMIN_PASSWORD` | Sí | Contraseña inicial, mínimo 16 caracteres; usa una aleatoria fuerte. |
| `CORS_ORIGINS` | Sí | Dominio real, por ejemplo `["https://docuintel.empresa.com"]`. |
| `VITE_API_BASE_URL` | Sí | En producción con frontend Nginx usa `/api`. |
| `FRONTEND_PORT` | Sí si no usas 8080 | Puerto host donde escucha el frontend. |
| `AI_BASE_URL` / `AI_MODEL` | Opcional | Servidor LLM compatible OpenAI. |
| `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` | Opcional | Servidor de embeddings. |
| `EMBEDDING_FALLBACK_TO_HASH` | Recomendado revisar | `false` en producción si quieres fallar cuando embeddings reales no estén disponibles. |
| `WATCHER_BACKEND` | Sí | `polling` para Docker Desktop, NAS o carpetas de red; `native` solo si inotify es fiable. |
| `APP_UID` / `APP_GID` | Recomendado | UID/GID del usuario que debe poder escribir en `data/files` y `data/input`. |

Generar secretos:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

No subas `.env.production` a git.

## 5. Preparación del servidor

### 5.1 Linux

```bash
sudo mkdir -p /opt/docu-intel
sudo chown -R "$USER:$USER" /opt/docu-intel
cd /opt/docu-intel
git clone <REPO_URL> .
mkdir -p data/files data/input backups
mkdir -p data/input/presupuestos data/input/pedidos data/input/facturas data/input/planos data/input/imagenes data/input/otros
```

Si vas a ejecutar contenedores como UID/GID 10001:

```bash
sudo chown -R 10001:10001 data/files data/input
```

### 5.2 Windows Server o Docker Desktop

```powershell
cd C:\Servicios
git clone <REPO_URL> docu-intel
cd docu-intel
New-Item -ItemType Directory -Force data\files,data\input,backups
New-Item -ItemType Directory -Force data\input\presupuestos,data\input\pedidos,data\input\facturas,data\input\planos,data\input\imagenes,data\input\otros
Copy-Item .env.production.example .env.production
```

En Windows deja `WATCHER_BACKEND=polling`.

## 6. Construcción y arranque

Linux/macOS:

```bash
export DOCUINTEL_ENV_FILE=.env.production
docker compose --env-file .env.production -f docker-compose.prod.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

Windows PowerShell:

```powershell
$env:DOCUINTEL_ENV_FILE=".env.production"
docker compose --env-file .env.production -f docker-compose.prod.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

Ver servicios:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

El backend ejecuta automáticamente:

```bash
alembic upgrade head
```

antes de levantar Uvicorn.

## 7. Exposición HTTP/HTTPS

### 7.1 Opción simple: puerto del frontend

Por defecto:

```env
FRONTEND_PORT=8080
VITE_API_BASE_URL=/api
```

La app queda disponible en:

```text
http://SERVIDOR:8080
```

Nginx del contenedor frontend reenvía `/api/*` al backend interno.

### 7.2 Producción con reverse proxy

Recomendado:

```text
https://docuintel.empresa.com -> http://127.0.0.1:8080
```

Ejemplo Caddy:

```caddyfile
docuintel.empresa.com {
  reverse_proxy 127.0.0.1:8080
  encode gzip
}
```

Ejemplo Nginx host:

```nginx
server {
  listen 80;
  server_name docuintel.empresa.com;
  return 301 https://$host$request_uri;
}

server {
  listen 443 ssl http2;
  server_name docuintel.empresa.com;

  ssl_certificate /etc/letsencrypt/live/docuintel.empresa.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/docuintel.empresa.com/privkey.pem;

  client_max_body_size 2g;

  location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

Si subes ficheros muy grandes desde navegador, ajusta `client_max_body_size`. Para ingesta masiva, usa `data/input`, no subida web.

## 8. Primer acceso

El backend crea un admin si no existe:

- email: `ADMIN_EMAIL`
- contraseña: `ADMIN_PASSWORD`

Después del primer login:

1. Crea usuarios nominales desde Administración.
2. Cambia o desactiva credenciales temporales.
3. Configura reglas de notificación.
4. Comprueba salud del sistema.
5. Ejecuta una ingesta pequeña de prueba.

## 9. Validación postdespliegue

### 9.1 Salud de contenedores

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

Esperado:

- `postgres`: healthy
- `redis`: healthy
- `backend`: healthy
- `watcher`: healthy
- `worker`: up
- `ocr-worker`: up
- `frontend`: up

### 9.2 Salud HTTP

```bash
curl -fsS http://localhost:8080
curl -fsS http://localhost:8000/health
```

En producción el backend no debería publicarse al exterior. El segundo comando se usa si estás en el host o si has publicado temporalmente el puerto.

### 9.3 Readiness interno

Desde la UI:

```text
Administración -> Sistema / Operativa -> Readiness
```

Desde API:

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  https://docuintel.empresa.com/api/admin/production/readiness
```

Estado esperado:

```json
{"status":"ready"}
```

### 9.4 Flujo funcional mínimo

1. Copia un PDF o TXT pequeño a `data/input/otros`.
2. Espera a que watcher lo registre.
3. Abre `Documentos`.
4. Verifica estado `processed`, `needs_review` o `failed`.
5. Abre el detalle documental.
6. Comprueba texto OCR, timeline y entidades.
7. Ejecuta una búsqueda textual.
8. Revisa `Jobs` y `Bandeja`.

## 10. Ingesta documental

Carpetas recomendadas:

```text
data/input/presupuestos
data/input/pedidos
data/input/facturas
data/input/planos
data/input/imagenes
data/input/otros
```

Buenas prácticas:

- Copia archivos completos, no edites dentro de `data/input` mientras watcher está activo.
- Para cargas grandes, copia primero a una carpeta temporal y mueve al destino al final.
- En carpetas de red usa `WATCHER_BACKEND=polling`.
- Ajusta `WATCHER_MAX_FILES_PER_TICK` si entran miles de documentos.
- Mantén `INGESTION_STABLE_SECONDS` y `WATCHER_SETTLE_SECONDS` altos si los archivos llegan por red lenta.

Pausar ingesta desde API:

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" \
  https://docuintel.empresa.com/api/admin/queues/pause
```

Reanudar:

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" \
  https://docuintel.empresa.com/api/admin/queues/resume
```

## 11. IA, OCR y embeddings

Docu-Intel puede funcionar sin LLM externo, pero algunas respuestas serán más básicas.

### 11.1 LLM local compatible OpenAI

```env
AI_PROVIDER=local_openai_compatible
AI_BASE_URL=http://host.docker.internal:1234/v1
AI_MODEL=qwen2.5-32b-instruct
AI_API_KEY=
```

Si el LLM está en otro host:

```env
AI_BASE_URL=http://10.0.0.50:1234/v1
```

### 11.2 Embeddings

```env
EMBEDDING_PROVIDER=local_openai_compatible
EMBEDDING_BASE_URL=http://10.0.0.50:1234/v1
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIMENSIONS=1024
EMBEDDING_FALLBACK_TO_HASH=false
```

Usa `EMBEDDING_FALLBACK_TO_HASH=true` solo si aceptas degradación temporal de búsqueda semántica.

### 11.3 OCR

OCR se ejecuta en los workers Python con PaddleOCR. Para escaneos pesados:

```env
OCR_WORKER_CONCURRENCY=1
OCR_WORKER_MEM_LIMIT=6g
OCR_WORKER_CPUS=4
```

Sube concurrencia solo después de medir RAM.

## 12. Escalado

### 12.1 Más workers

Puedes aumentar réplicas de workers si el host tiene CPU/RAM:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --scale worker=2 --scale ocr-worker=2
```

Mantén `OCR_WORKER_CONCURRENCY=1` si los documentos escaneados son grandes.

### 12.2 Separar componentes

Para despliegues mayores:

- PostgreSQL gestionado externo con extensión `pgvector`.
- Redis gestionado externo.
- Varios hosts de worker apuntando al mismo PostgreSQL/Redis.
- Almacenamiento compartido para `data/files` si hay varios backends/workers.

No escales varios backends si cada uno ve un `data/files` distinto.

## 13. Backups

Debes respaldar:

1. PostgreSQL.
2. `data/files`.
3. `.env.production` en un gestor seguro de secretos.
4. Opcional: `data/input` si contiene documentos aún no procesados.

### 13.1 Backup con script PowerShell

```powershell
.\scripts\backup.ps1 -EnvFile .env.production
```

Crea:

```text
backups/YYYYMMDD_HHMMSS/docuintel.dump
backups/YYYYMMDD_HHMMSS/files/
```

### 13.2 Backup manual Linux

```bash
mkdir -p backups/$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=backups/$(date +%Y%m%d_%H%M%S)

docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U app -d docuintel -Fc > "$BACKUP_DIR/docuintel.dump"

rsync -a --delete data/files/ "$BACKUP_DIR/files/"
```

### 13.3 Retención recomendada

- Diario: 7-14 días.
- Semanal: 4-8 semanas.
- Mensual: 6-12 meses.
- Copia externa/offsite: obligatoria para producción.

### 13.4 Prueba de restore

Un backup no es válido hasta restaurarlo en un entorno separado.

PowerShell:

```powershell
.\scripts\restore.ps1 -BackupDir backups\YYYYMMDD_HHMMSS -EnvFile .env.production
```

Linux manual:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  pg_restore -U app -d docuintel --clean --if-exists < backups/YYYYMMDD_HHMMSS/docuintel.dump

rsync -a --delete backups/YYYYMMDD_HHMMSS/files/ data/files/
```

Haz pruebas de restore antes de cargar documentación real.

## 14. Actualizaciones

Proceso recomendado:

1. Anunciar ventana de mantenimiento.
2. Pausar ingesta.
3. Crear backup.
4. Descargar nueva versión.
5. Revisar cambios de `.env.production.example`.
6. Reconstruir imágenes.
7. Levantar servicios.
8. Validar health/readiness.
9. Reanudar ingesta.

Comandos:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec backend \
  python -m app.scripts.pause_ingestion
```

Si no existe script dedicado, usa la UI o API de pausa de colas.

Backup:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U app -d docuintel -Fc > backups/pre_upgrade.dump
```

Despliegue:

```bash
git pull
docker compose --env-file .env.production -f docker-compose.prod.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

Ver logs de migración:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f backend
```

## 15. Rollback

Si falla una actualización:

1. Detén servicios nuevos:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml down
```

2. Vuelve al commit/imagen anterior:

```bash
git checkout <COMMIT_ESTABLE>
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

3. Si hubo migración destructiva o datos corruptos, restaura backup.

No hagas rollback de código sin revisar si Alembic aplicó migraciones incompatibles.

## 16. Monitorización

Mínimo operativo:

- Healthcheck Docker de `backend`, `postgres`, `redis`, `watcher`.
- Alertas por disco bajo.
- Alertas por contenedor reiniciando.
- Alertas por cola atascada.
- Alertas por OCR fallido.
- Backup diario con verificación.

Endpoints útiles:

```text
GET /health
GET /admin/system/health
GET /admin/production/readiness
GET /admin/operations/overview
GET /admin/queues
GET /admin/storage/integrity
GET /admin/audit-logs
```

Logs:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f backend
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f worker
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f ocr-worker
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f watcher
```

## 17. Seguridad

Checklist mínimo antes de producción:

- `ENVIRONMENT=production`.
- Todos los secretos cambiados.
- `.env.production` fuera de git.
- TLS activo.
- PostgreSQL y Redis sin puertos públicos.
- `CORS_ORIGINS` solo con dominios reales.
- Usuarios nominales; no compartir admin.
- Backups cifrados o almacenados en ubicación segura.
- Firewall solo con 80/443 públicos.
- Acceso SSH restringido.
- Actualización periódica de imágenes base.
- Revisión de logs de auditoría.

Opcional recomendado:

- Autenticación por VPN o Zero Trust delante del reverse proxy.
- Snapshot de volumen antes de upgrades.
- Escaneo de imágenes con Docker Scout, Trivy o herramienta equivalente.
- Rotación programada de `JWT_SECRET`, API keys e integration keys.

## 18. Despliegues por entorno

### 18.1 VPS o VM única

Usa `docker-compose.prod.yml` tal cual. Expón solo el frontend vía reverse proxy.

### 18.2 Portainer

1. Crea stack nuevo.
2. Usa `docker-compose.prod.yml`.
3. Sube `.env.production` como env file o variables del stack.
4. Monta rutas persistentes `data/files` y `data/input`.
5. Publica `FRONTEND_PORT`.

### 18.3 Coolify

1. Crea recurso Docker Compose.
2. Usa el repositorio y `docker-compose.prod.yml`.
3. Configura variables del `.env.production` en secrets.
4. Publica solo `frontend`.
5. Activa HTTPS en Coolify.

### 18.4 NAS

Requisitos:

- Docker Compose v2.
- Volumen con buen rendimiento de I/O.
- `WATCHER_BACKEND=polling`.
- Backups hacia otro dispositivo.

Evita NAS con poca RAM para OCR pesado.

### 18.5 Cloud con base de datos gestionada

Puedes sustituir `postgres` por un PostgreSQL gestionado si:

- Tiene extensión `pgvector`.
- `DATABASE_URL` apunta al servicio externo.
- Latencia entre backend/workers y DB es baja.
- Backups gestionados están activados.

Si quitas el servicio `postgres` del compose, elimina dependencias `depends_on` o usa un override.

## 19. Troubleshooting

### Backend no arranca

Ver logs:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs backend
```

Causas típicas:

- `JWT_SECRET` o `ADMIN_PASSWORD` inválidos en producción.
- `DATABASE_URL` no coincide con `POSTGRES_PASSWORD`.
- Migración Alembic fallida.
- Carpetas sin permisos.

### Frontend carga pero API falla

Comprueba:

- `VITE_API_BASE_URL=/api` en build de frontend.
- `frontend/nginx.conf` proxy a `backend:8000`.
- Backend healthy.
- Reverse proxy no está eliminando `/api`.

### Watcher no ingesta

Comprueba:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs watcher
```

Revisa:

- `WATCHER_ENABLED=true`.
- Ficheros en subcarpetas de `data/input`.
- Permisos de escritura.
- Cola pausada.
- `INGESTION_MAX_PENDING_JOBS` alcanzado.

### OCR consume demasiada RAM

Reduce:

```env
OCR_WORKER_CONCURRENCY=1
OCR_WORKER_MEM_LIMIT=6g
WATCHER_MAX_FILES_PER_TICK=5
```

### Redis/Postgres reinician

Revisa disco, RAM y logs:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs postgres
docker compose --env-file .env.production -f docker-compose.prod.yml logs redis
```

### Archivos aparecen como huérfanos o faltantes

Ejecuta:

```text
Administración -> Mantenimiento -> Integridad de almacenamiento
```

o:

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  https://docuintel.empresa.com/api/admin/storage/integrity
```

## 20. Checklist final de producción

Antes de abrir a usuarios:

- [ ] `.env.production` revisado y sin placeholders.
- [ ] `docker compose ... config` no muestra errores.
- [ ] `docker compose ... ps` muestra servicios healthy/up.
- [ ] HTTPS activo.
- [ ] Dominio real en `CORS_ORIGINS`.
- [ ] Primer login admin probado.
- [ ] Usuario no admin probado.
- [ ] Ingesta de documento de prueba correcta.
- [ ] Búsqueda textual/híbrida probada.
- [ ] OCR de un PDF escaneado probado.
- [ ] Backup ejecutado.
- [ ] Restore probado en entorno separado.
- [ ] Alertas de disco/colas configuradas.
- [ ] Firewall revisado.
- [ ] Runbook de actualización y rollback validado.

## 21. Comandos de referencia

Arrancar:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

Parar:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml stop
```

Apagar sin borrar datos:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml down
```

Ver logs:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f
```

Recrear un servicio:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build backend
```

Entrar al backend:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec backend sh
```

Ejecutar migraciones manualmente:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec backend alembic upgrade head
```

Estado de colas:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs worker --tail=200
```

## 22. Qué no hacer

- No uses `docker-compose.yml` base para producción.
- No publiques PostgreSQL ni Redis a internet.
- No uses `localhost:5175` como producción; eso es servidor Vite de desarrollo.
- No cargues cientos de GB desde el navegador.
- No borres `postgres_data`, `redis_data` ni `data/files` sin backup.
- No cambies `JWT_SECRET` sin planificar cierre de sesiones.
- No hagas upgrade sin backup previo.
- No declares producción lista sin probar restore.

