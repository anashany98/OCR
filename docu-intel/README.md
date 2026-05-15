# Docu-Intel

Aplicación web interna de inteligencia documental para ingestar presupuestos, pedidos, facturas, albaranes, planos, imágenes, PDFs y Excels. El estado actual cubre Fase 1, Fase 2 básica, Fase 3 inicial, Fase 4 inicial y bloque operativo de Fase 5: autenticación, subida y escaneo, cola Celery, extracción OCR/texto, clasificación, extracción inicial de presupuestos/pedidos, embeddings locales, búsqueda textual/semántica/híbrida, chat IA local con tools internas controladas, extracción verificable de planos, alertas, auditoría y reprocesado avanzado.

## Arranque con Docker Compose

```bash
cd docu-intel
docker compose up --build
```

Servicios principales:

- Backend FastAPI: `http://localhost:8000`
- Frontend React: `http://localhost:5173` o `http://localhost:5174` si el puerto 5173 está ocupado por un servidor local
- PostgreSQL + pgvector: servicio interno `postgres:5432`
- Redis: servicio interno `redis:6379`
- Watcher de ingesta 24h: servicio `watcher`, sin puerto público
- Worker Celery: escucha colas `text_fast`, `ocr_heavy`, `embeddings` y `maintenance`

El proyecto incluye un `.env` local para facilitar el primer arranque y un `.env.example` como plantilla. Cambia secretos, URLs y credenciales antes de usarlo en una red de empresa.

## Usuario Admin

En el arranque del backend se crea un admin si no existe:

- Email: `admin@local`
- Contraseña: `admin123`

Cambia `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_NAME` y `JWT_SECRET` antes de usarlo en una red de empresa.

## Configurar IA Local

La ruta `/ai/ask` usa primero tools internas del backend y solo envía al modelo local el contexto documental recuperado. Si `AI_BASE_URL` o `AI_MODEL` no están disponibles, responde con una plantilla grounded del backend sin inventar datos. Variables:

```env
AI_PROVIDER=local_openai_compatible
AI_BASE_URL=http://host.docker.internal:1234/v1
AI_MODEL=qwen2.5-32b-instruct
AI_API_KEY=
```

No se permite SQL libre generado por el modelo. Las tools disponibles están implementadas en backend: búsqueda documental, presupuestos aceptados sin pedido, pedidos por número, entidades, planos básicos, duplicados y documentos con revisión OCR.

## API Segura para IA Intermedia

La integración servidor-servidor vive en `/integrations/v1`. Está pensada para que otra herramienta ejecute su propia IA y use Docu-Intel solo como proveedor de tools controladas.

Autenticación:

```http
X-DocuIntel-API-Key: dev-secret
X-Technician-Id: tecnico-17
X-Technician-Name: Nombre opcional
```

Configuración:

```env
INTEGRATION_CLIENTS=external-tool:dev-secret:read,upload
INTEGRATION_ENQUEUE_UPLOADS=true
INTEGRATION_RATE_LIMIT_PER_MINUTE=120
INTEGRATION_SESSION_EXPIRE_SECONDS=3600
```

Endpoints principales:

- `GET /integrations/v1/manifest`: tools disponibles y reglas para la IA intermedia.
- `POST /integrations/v1/sessions`: crea una sesión firmada limitada a un presupuesto/carpeta (`budget_scope_id`).
- `POST /integrations/v1/tools/execute`: ejecuta una tool controlada.
- `POST /integrations/v1/documents/upload`: sube documentos desde la herramienta externa.
- `GET /integrations/v1/documents/{id}/status` y `GET /integrations/v1/jobs/{id}`: consulta estado.
- Todas las llamadas quedan limitadas por técnico/cliente mediante `INTEGRATION_RATE_LIMIT_PER_MINUTE`.

Flujo recomendado para la otra herramienta:

```http
POST /integrations/v1/sessions
X-DocuIntel-API-Key: dev-secret
X-Technician-Id: tecnico-17
Content-Type: application/json

{"budget_code": "245745"}
```

La respuesta devuelve `session_token`, `budget_scope_id`, `budget_code`, caducidad y si la sesión permite importes. Las consultas posteriores envían:

```http
Authorization: Bearer <session_token>
X-DocuIntel-API-Key: dev-secret
X-Technician-Id: tecnico-17
```

Si hay sesión activa, Docu-Intel limita las tools al `budget_scope_id` firmado. Si el usuario menciona otro presupuesto en la pregunta, no se cambia de scope.

Políticas iniciales:

- `operario_minimo`: política por defecto. Permite consultar presupuestos por número exacto sin precios. Redacta importes estructurados y OCR como `[IMPORTE OCULTO]`.
- `precios_autorizados`: permite importes para técnicos asignados explícitamente.

Regla crítica: la redacción se aplica antes de entregar contexto a la IA externa. La IA no recibe precios si el técnico no tiene permiso.

## Aislamiento por Presupuesto

El aislamiento principal de este proyecto es por presupuesto/carpeta, no por hotel/cadena. Una carpeta como `/srv/docuintel/inbox/245745` o `/data/input/presupuestos/245745` se registra como `budget_scope` con `budget_code=245745`.

Modelo operativo:

```text
api_client / tecnico
  -> api_client_budget_scopes
    -> budget_scope
      -> documents
        -> chunks / OCR / entidades / planos
```

Los permisos de `api_client_budget_scopes` son explícitos:

- `can_query`: permite crear sesión y consultar ese presupuesto.
- `can_see_amounts`: permite importes solo si también la política del técnico lo autoriza.

Por seguridad, `can_see_amounts` es `false` por defecto. Hoteles/cadenas quedan aparcados para un futuro proyecto y el código existente se mantiene por compatibilidad, pero no es el eje de integración actual.

Endpoints admin mínimos para operar scopes:

- `GET /admin/budget-scopes`: listar presupuestos/carpeta registrados.
- `POST /admin/budget-scopes`: crear o actualizar un scope por `budget_code`.
- `GET /admin/budget-scopes/{id}/client-permissions`: ver permisos de clientes API.
- `POST /admin/budget-scopes/{id}/client-permissions`: conceder o cambiar `can_query` y `can_see_amounts`.

## Aislamiento por Cadena/Hotel

Docu-Intel aplica un scope documental centralizado antes de devolver documentos a usuarios internos, técnicos externos o la IA intermedia:

- Modelo jerárquico: `cadena -> hotel`.
- Los documentos se asignan mediante reglas de carpeta o asignación manual.
- Si un documento no tiene cadena/hotel válido queda en cuarentena y no aparece en búsquedas ni tools de integración.
- Los `denied_tags` del perfil bloquean siempre el documento, aunque el usuario tenga acceso al hotel.
- `admin` conserva acceso total para operar y recuperar documentos.

Gestión desde `Administración`:

- `Cadenas/Hoteles`: crear cadenas y hoteles.
- `Reglas de carpetas`: crear patrones como `/presupuestos/cadena/hotel/`, asociar cadena/hotel/tags y reaplicar reglas.
- `Perfiles/Grupos`: definir hoteles/cadenas permitidas, bloqueo de tags y permisos de precios/búsqueda.
- `Cuarentena`: asignar manualmente documentos sin scope.
- `Tags sensibles`: catálogo inicial de tags como `contabilidad`, `administracion` o `rrhh`.

La API admin disponible incluye `/admin/hotel-chains`, `/admin/hotels`, `/admin/folder-rules`, `/admin/folder-rules/apply`, `/admin/document-access/{document_id}`, `/admin/access-groups`, `/admin/quarantine-documents` y `/admin/sensitive-tags`.

## Configurar Embeddings Locales

Los chunks se guardan en `document_chunks.embedding` con dimensión 1024 para BGE-M3. Para usar embeddings reales con un servidor local compatible OpenAI:

```env
EMBEDDING_PROVIDER=local_openai_compatible
EMBEDDING_BASE_URL=http://host.docker.internal:1234/v1
EMBEDDING_MODEL=bge-m3
EMBEDDING_API_KEY=
EMBEDDING_DIMENSIONS=1024
EMBEDDING_TIMEOUT_SECONDS=10
EMBEDDING_FALLBACK_TO_HASH=true
```

El backend llama a `POST /embeddings` con `model` e `input`. Si el servidor local no está disponible y `EMBEDDING_FALLBACK_TO_HASH=true`, usa el fallback determinista local para no bloquear la ingesta.

## Meter Documentos

Para pocos archivos puedes subir desde la pantalla `Documentos`. Para cargas grandes o históricos de cientos de GB, no uses el navegador: copia o sincroniza los documentos directamente en las carpetas montadas de `data/input`. El servicio `watcher` las vigila 24h y manda a OCR cualquier archivo nuevo cuando deja de cambiar.

```text
data/input/presupuestos
data/input/pedidos
data/input/facturas
data/input/planos
data/input/imagenes
data/input/otros
```

Parámetros relevantes:

```env
INGESTION_STABLE_SECONDS=30
FILE_STORAGE_STRATEGY=auto
WATCHER_ENABLED=true
WATCHER_BACKEND=polling
WATCHER_RECURSIVE=true
WATCHER_POLL_SECONDS=2
WATCHER_SETTLE_SECONDS=5
WATCHER_RESCAN_INTERVAL_SECONDS=3600
WATCHER_MAX_FILES_PER_TICK=10
```

- `INGESTION_STABLE_SECONDS`: evita procesar un archivo mientras todavía se está copiando.
- `WATCHER_SETTLE_SECONDS`: agrupa eventos rápidos del filesystem antes de intentar registrar el archivo.
- `WATCHER_BACKEND`: usa `polling` para Docker Desktop/Windows o carpetas de red; usa `native` en servidores Linux si los eventos inotify son fiables.
- `WATCHER_RESCAN_INTERVAL_SECONDS`: scan periódico para recuperar eventos perdidos.
- `WATCHER_MAX_FILES_PER_TICK`: limita cuántos archivos registra por vuelta para no saturar la BD/cola.
- `FILE_STORAGE_STRATEGY=auto`: intenta hardlink dentro de `/data/files` para no duplicar cientos de GB si el filesystem lo permite; si no puede, hace copia normal. Usa `copy` si los documentos de entrada pueden modificarse después de entrar.

## Lanzar Escaneo Manual

El watcher cubre la operación normal 24h. El escaneo manual sigue disponible para forzar una pasada completa o recuperar documentos añadidos con el watcher apagado.

Desde el frontend: `Documentos -> Escanear carpetas`.

Desde API:

```bash
curl -X POST http://localhost:8000/ingestion/scan \
  -H "Authorization: Bearer <TOKEN>"
```

## Reprocesar Documentos

Desde el visor o tabla de documentos pulsa `Reprocesar`.

Desde API:

```bash
curl -X POST http://localhost:8000/documents/<ID>/reprocess \
  -H "Authorization: Bearer <TOKEN>"
```

## Pipeline Fase 1

1. Calcula SHA256.
2. Registra duplicados con `status=duplicate`.
3. Guarda originales en `/app/data/files/<sha-prefix>/<sha256>.<ext>` usando la estrategia `FILE_STORAGE_STRATEGY`.
4. Crea `documents` y `extraction_jobs`.
5. Envía la extracción a Celery.
6. Extrae texto de PDFs digitales con PyMuPDF.
7. Renderiza y pasa PaddleOCR cuando el PDF no tiene texto suficiente.
8. Procesa imágenes con PaddleOCR.
9. Procesa Excel con pandas/openpyxl.
10. Guarda páginas, bloques, chunks con embeddings locales reales si están configurados, o fallback hash local si no hay servidor disponible.

## Fase 2 Implementada

- Extracción básica de presupuestos: número, cliente, fecha, total, moneda, estado aceptado/pendiente/cancelado y líneas con referencia cuando el patrón es claro.
- Extracción básica de pedidos: número, proveedor, cliente, fecha, total, presupuesto relacionado mencionado y líneas.
- Persistencia en `budgets`, `budget_lines`, `orders`, `order_lines` y `document_entities`.
- Visor de documento con entidades detectadas.
- Dashboard con lista de errores OCR y documentos que requieren revisión.
- Endpoints de líneas: `/budgets/{id}/lines` y `/orders/{id}/lines`.

## Fase 3 Implementada

- Embeddings locales reales mediante servidor OpenAI-compatible (`POST /embeddings`) con BGE-M3 u otro modelo de 1024 dimensiones.
- Fallback determinista local de 1024 dimensiones para mantener la plataforma offline si el servidor de embeddings no está configurado o falla.
- Búsqueda semántica: `POST /search/semantic`.
- Búsqueda híbrida: `POST /search/hybrid`, combinando coincidencias textuales y similitud semántica.
- Chat IA: `POST /ai/ask`, con selección de intención en backend y ejecución de tools internas controladas.
- Guardado de historial en `ai_questions`, `ai_answers` y `ai_answer_sources`.
- Respuestas con secciones obligatorias: `Respuesta`, `Datos`, `Fuentes`, `Confianza` y `Advertencias`.
- Frontend conectado para búsqueda textual/semántica/híbrida y panel de Chat IA con fuentes.

## Fase 4 Implementada

- Extracción de escala escrita en planos, por ejemplo `1:50` o `1:100`.
- Extracción de cotas textuales con unidad `m`, `cm` y `mm`, guardando siempre `confidence`.
- Extracción de habitaciones con superficies OCR escritas en `m2`/`m²`, guardadas como `source=ocr_text`.
- Persistencia en `plans`, `plan_rooms` y `plan_dimensions` durante el pipeline de procesamiento.
- Regla crítica: no se convierten geometrías/píxeles a metros si no hay escala válida o cota fiable.
- Planos sin escala válida quedan marcados para revisión y aparecen en el dashboard.
- Frontend de Planos con detalle, cotas, habitaciones, edición manual de escala y edición de habitaciones.
- El chat IA puede consultar medidas de habitaciones estructuradas con fuentes; si no hay datos suficientes, mantiene la respuesta anti-invención.

## Fase 5 Operativa Implementada

- Alertas avanzadas en `/admin/alerts`: presupuestos aceptados sin pedido, pedidos sin presupuesto, OCR/revisión, planos sin escala, duplicados y jobs fallidos.
- Métricas de volumen en `/admin/processing-metrics`: documentos por estado/tipo, jobs por estado y total de eventos auditados.
- Auditoría consultable en `/admin/audit-logs`, con filtros por acción, entidad y usuario.
- Reprocesado avanzado en `/documents/reprocess-bulk`, filtrando por estado, tipo documental, carpeta origen o IDs concretos.
- Modos de reprocesado reales: `full` rehace parser/OCR y datos dependientes; `ocr` rehace parser/OCR y reconstruye dependientes; `classification` reutiliza páginas ya extraídas y recalcula clasificación, entidades, presupuestos/pedidos y planos; `embeddings` reconstruye solo `document_chunks`.
- API de integración `/integrations/v1` para IA intermedia con API key, sesiones firmadas por presupuesto, políticas por técnico, redacción de precios y tools controladas.
- Aislamiento por `budget_scope_id` aplicado a la integración externa. El aislamiento por cadena/hotel queda disponible en la base pero se aparca para un proyecto posterior.
- Panel admin para cadenas/hoteles, reglas de carpeta, grupos de acceso, cuarentena y tags sensibles.
- Índices Alembic adicionales para listados grandes, auditoría, jobs, alertas y filtros frecuentes.
- Panel de Administración actualizado con alertas, métricas, auditoría, controles de reprocesado y gobierno documental.
- Ingesta masiva por carpetas con servicio `watcher`, detección de archivos estables, scan inicial y rescan periódico.
- Storage `auto` con hardlink/fallback a copia para reducir duplicación de datos en cargas de cientos de GB.
- Trazabilidad operativa en `/admin/operations-status`, `/admin/watched-files` y `/admin/ingestion-events`.
- Informe de mantenimiento en `/admin/maintenance-report`, con estado de jobs, watchdog y disco.
- Simulador admin de permisos en `/admin/access-explain` para comprobar por qué un usuario/técnico puede o no ver un documento.
- Grafo documental básico en `/admin/documents/{document_id}/graph`, enlazando presupuesto-pedido y referencias compartidas.
- Enrutado Celery por carga: OCR/PDF/planos a `ocr_heavy`, Excel/texto a `text_fast`, embeddings a `embeddings` y escaneos a `maintenance`.

## Limitaciones Conocidas

- Los embeddings reales dependen de que el servidor local exponga `/v1/embeddings`; con el fallback activado, la ingesta sigue funcionando aunque ese servidor no esté disponible.
- Si el servidor local compatible OpenAI no está levantado, `/ai/ask` devuelve una respuesta grounded generada por backend con las fuentes recuperadas.
- La API de integración no descarga originales en v1; devuelve metadatos, fuentes y excerpts saneados.
- Los documentos existentes quedan fuera del scope hasta crear reglas y ejecutar `Reaplicar reglas`, o asignarlos manualmente desde `Administración -> Cuarentena`.
- La extracción estructurada avanzada de presupuestos/pedidos y la relación presupuesto-pedido por similitud se completan en Fase 5.
- La extracción geométrica avanzada de planos desde líneas/polígonos queda como mejora posterior; la Fase 4 actual solo guarda medidas textuales OCR o correcciones humanas.
- PaddleOCR CPU hace la imagen Docker más pesada y puede tardar en el primer arranque.
- El borrado de documentos es lógico; los archivos originales no se eliminan por defecto.
- La subida HTTP desde navegador no está pensada para cientos de GB; para ese caso usa carpetas `data/input` o una sincronización externa hacia esas carpetas.
- Si `FILE_STORAGE_STRATEGY=auto` usa hardlinks, no modifiques en sitio los documentos ya ingeridos en `data/input`; si necesitas máxima independencia física del archivo guardado, usa `FILE_STORAGE_STRATEGY=copy`.

## Desarrollo Local

Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pytest
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```
