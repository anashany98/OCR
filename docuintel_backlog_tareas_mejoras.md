# Backlog de arreglos y mejoras — Docu-Intel

**Objetivo:** fusionar y ordenar la lista propia + la revisión de Claude en un plan de tareas ejecutable para mejorar la app antes de usarla con documentos reales.

**Stack observado:** FastAPI, React/Vite, PostgreSQL + pgvector, Redis, Celery, watcher, PaddleOCR, embeddings locales, IA local/OpenAI-compatible, Docker/Coolify.

---

## Actualizacion 2026-05-21

Tanda aplicada tras la revision completa:

- La busqueda textual ya aplica `budget_scope_id` dentro de SQL cuando el filtro existe.
- Las tools de integracion con sesion firmada inyectan el `budget_scope_id` antes de buscar, evitando perder resultados por filtrar despues del limite.
- La cache de respuestas IA incluye una firma del scope efectivo del usuario.
- Se anadio `scripts/verify-backup.ps1` para validar dump, archivos y `manifest.json`.
- Se anadio workflow CI con migraciones Alembic, tests backend, tests frontend y build.
- Se implemento reprocesado OCR por pagina con jobs `reprocess:ocr_page:<pagina>`, actualizacion aislada de pagina/bloques/chunks y fallo de pagina sin marcar todo el documento como `failed`.

Pendiente de sprints posteriores:

- Edicion OCR/extraccion versionada en UI.
- Perfiles por proveedor/formato para extraccion estructurada avanzada.
- Refactor grande de `backend/app/api/routes/admin.py` y `frontend/src/pages/AdminPage.tsx`.
- Prueba manual de restore en una instancia separada con datos reales o anonimizados.

---

## Leyenda

| Prioridad | Significado |
|---|---|
| **P0 — Crítico** | Bloquea uso con documentos reales o puede causar fuga/pérdida de datos. |
| **P1 — Alto** | Necesario para estabilidad, rendimiento u operación seria. |
| **P2 — Medio** | Mejora producto, mantenibilidad y usabilidad. |
| **P3 — Bajo / futuro** | Mejora avanzada o refactor no urgente. |

| Origen | Significado |
|---|---|
| **Ambos** | Coincide con mi revisión y con Claude. |
| **Claude** | Lo aportó Claude y se considera válido. |
| **Revisión propia** | Lo añadí o lo considero más importante que Claude. |
| **Corregido de Claude** | Claude lo dijo, pero había que matizarlo o reordenarlo. |

---

# Resumen ejecutivo

La app tiene una arquitectura sólida, pero antes de producción hay que priorizar:

1. **Aislamiento por presupuesto**.
2. **Seguridad de login/cookies/API externa**.
3. **Control de archivos pesados o falsos**.
4. **Backup + restore probado en Linux/Coolify**.
5. **Búsqueda vectorial usando pgvector correctamente en SQL**.
6. **OCR por página y reprocesado parcial**.
7. **Workers Celery separados por carga**.
8. **Healthchecks reales para IA/embeddings**.
9. **Watcher que detecte modificaciones, no solo archivos nuevos**.
10. **Tests anti-fuga entre presupuestos**.

---

# Sprint 0 — Seguridad crítica y aislamiento

> Hacer antes de meter documentos sensibles o abrir la app a usuarios internos.

| ID | Prioridad | Tarea | Origen | Zona afectada | Criterio de terminado |
|---|---|---|---|---|---|
| SEC-001 | P0 | Cambiar cookie de auth a `secure=True` en producción | Revisión propia | `backend/app/api/routes/auth.py` | En producción la cookie se emite con `Secure`; en local puede ser configurable. |
| SEC-002 | P0 | Revisar `SameSite` y política de cookies | Revisión propia | Auth/backend | Cookie con `SameSite=Lax` o `Strict` según necesidad; documentado. |
| SEC-003 | P0 | Añadir rate limit específico a `/auth/login` | Revisión propia | Auth/backend/middleware | 5-10 intentos por IP/email; bloqueo temporal; log de fallos. |
| SEC-004 | P0 | Validar permisos al subir documento por `budget_code` desde API externa | Revisión propia | `backend/app/api/routes/integrations.py` | Si el cliente API no tiene permiso sobre ese presupuesto, devuelve 403. |
| SEC-005 | P0 | Hacer obligatorio el filtro `budget_scope_id` en toda búsqueda documental | Revisión propia | Search/AI/Integrations | Ninguna búsqueda semántica, híbrida o tool puede ejecutarse sin scope autorizado. |
| SEC-006 | P0 | Tests anti-fuga entre presupuestos | Ambos | Tests backend | Test: usuario/API con presupuesto A no puede recuperar chunks de presupuesto B. |
| SEC-007 | P0 | Redacción obligatoria de importes antes de enviar contexto a IA | Revisión propia | AI/redaction/integrations | La IA nunca recibe importes si el técnico no tiene permiso. |
| SEC-008 | P0 | Registrar qué chunks se enviaron a la IA | Revisión propia | AI/audit DB | Cada respuesta IA guarda chunk IDs, documento, página y usuario/técnico. |
| SEC-009 | P0 | Añadir tests de importes ocultos | Revisión propia | Tests AI/security | La IA no puede reconstruir ni inferir importes ocultos. |
| SEC-010 | P0 | Validar permisos efectivos en API externa con `session_token` | Revisión propia | Integrations v1 | Toda tool ejecutada con sesión queda limitada al `budget_scope_id` firmado. |
| SEC-011 | P1 | Añadir CSRF si se opera principalmente con cookies | Revisión propia | Backend/frontend | Formularios sensibles protegidos o cambio claro a Bearer token. |
| SEC-012 | P1 | Redis con contraseña en producción | Claude | `docker-compose.prod.yml`, `.env.production` | Redis usa `--requirepass`; URLs actualizadas; no expuesto públicamente. |

---

# Sprint 1 — Control de archivos y seguridad de ingesta

| ID | Prioridad | Tarea | Origen | Zona afectada | Criterio de terminado |
|---|---|---|---|---|---|
| FILE-001 | P0 | Añadir límite máximo de upload HTTP | Revisión propia | Upload documentos/integrations | Rechaza archivos por encima de `MAX_UPLOAD_SIZE_MB`. |
| FILE-002 | P0 | Añadir límite máximo de páginas por PDF | Revisión propia | Parser PDF/OCR | PDF con más de `MAX_PDF_PAGES` queda bloqueado o requiere aprobación. |
| FILE-003 | P0 | Añadir límite de megapíxeles por imagen | Revisión propia | Parser imagen/OCR | Imagen gigante no tumba el worker OCR. |
| FILE-004 | P0 | Añadir límite de filas/hojas en Excel | Revisión propia | Parser Excel | Excel excesivo queda marcado como `needs_human_review` o bloqueado. |
| FILE-005 | P0 | Validación MIME/firma real | Ambos | `file_security.py` | PDF empieza por `%PDF`; PNG/JPG/XLSX válidos; no confiar solo en extensión. |
| FILE-006 | P0 | Bloquear `.doc` y `.docx` temporalmente o crear parser real | Ambos | `config.py`, `parsers/router.py` | `.doc/.docx` no cae en `parse_plain_text`; o parser real probado. |
| FILE-007 | P1 | Cuarentena lógica para archivos sospechosos | Revisión propia | Storage/ingestion | Archivo sospechoso no llega a OCR automáticamente. |
| FILE-008 | P1 | Detectar ejecutables renombrados con más firmas | Revisión propia | `file_security.py` | Bloquea MZ/ELF/Mach-O/scripts comunes aunque tengan extensión falsa. |
| FILE-009 | P1 | Guardar motivo de bloqueo en BD | Revisión propia | Documents/jobs | Usuario ve por qué un archivo fue rechazado. |
| FILE-010 | P2 | Panel de documentos bloqueados/cuarentena | Revisión propia | Frontend admin | Admin puede revisar, aprobar o descartar archivos sospechosos. |

---

# Sprint 2 — Celery, workers y watcher

| ID | Prioridad | Tarea | Origen | Zona afectada | Criterio de terminado |
|---|---|---|---|---|---|
| CEL-001 | P1 | Separar workers por cola también en local | Ambos | `docker-compose.yml` | `worker-fast`, `worker-heavy`, `worker-maintenance` separados. |
| CEL-002 | P1 | Mantener `ocr_heavy` con concurrencia baja | Ambos | Docker/Celery | OCR pesado corre con `--concurrency=1` o configurable. |
| CEL-003 | P1 | Test de enrutado por tipo documental | Corregido de Claude | Tests Celery | PDF/imagen/plano van a `ocr_heavy`; Excel/texto a `text_fast`. |
| CEL-004 | P1 | Revisar todos los `apply_async` de `process_document_task` | Corregido de Claude | Backend | Ningún enqueue usa cola por defecto incorrecta. |
| CEL-005 | P1 | Watcher debe detectar modificaciones por hash | Claude | `watcher.py`, ingestion service | Si cambia hash de archivo existente, se crea nueva versión o se reencola. |
| CEL-006 | P1 | Guardar `last_seen_at`, `mtime`, `size`, `file_hash` por origen | Revisión propia | DB modelo documentos/watched_files | Permite detectar nuevos, modificados, movidos y desaparecidos. |
| CEL-007 | P1 | Definir comportamiento ante archivo sobrescrito | Claude | Ingestion policy | Decidir: versionar, reprocesar o crear duplicado controlado. |
| CEL-008 | P1 | Scheduler fuera de `profiles` o documentado | Corregido de Claude | `docker-compose.yml`, README | Queda claro si se usa watcher, Celery Beat o ambos. |
| CEL-009 | P1 | Backpressure por cola | Revisión propia | Workers/admin | Si `ocr_heavy` se satura, el sistema limita nuevas tareas OCR. |
| CEL-010 | P2 | Métricas por cola | Revisión propia | Admin/metrics | Ver documentos/hora, tiempo medio OCR, errores por cola, ETA. |

---

# Sprint 3 — Backup, restore y despliegue Linux/Coolify

| ID | Prioridad | Tarea | Origen | Zona afectada | Criterio de terminado |
|---|---|---|---|---|---|
| OPS-001 | P0 | Crear `backup.sh` para Linux/Coolify | Ambos | `scripts/backup.sh` | Hace backup de PostgreSQL y `/data/files`. |
| OPS-002 | P0 | Crear `restore.sh` para Linux/Coolify | Ambos | `scripts/restore.sh` | Restaura BD y archivos en entorno limpio. |
| OPS-003 | P0 | Probar restore real | Revisión propia | Operación | Hay checklist y prueba documentada de restore. |
| OPS-004 | P1 | Compresión y rotación de backups | Ambos | Scripts/cron | Backups comprimidos, rotación por días/semanas. |
| OPS-005 | P1 | Alertar si backup falla o pesa demasiado poco | Revisión propia | Scripts/monitoring | Falla visible en admin/logs. |
| OPS-006 | P1 | Montar volumen de backups en producción | Claude | `docker-compose.prod.yml` | Backups no quedan dentro de contenedor efímero. |
| OPS-007 | P1 | Script de importación masiva por rsync/VPN | Claude | `scripts/import_initial.sh` | Importa histórico de 300GB con log, reintentos e integridad. |
| OPS-008 | P1 | Script de sync incremental | Claude | `scripts/sync_incremental.sh` | Copia nuevos/cambiados sin borrar origen. |
| OPS-009 | P1 | Check de integridad post-importación | Claude | `scripts/check_import_integrity.sh` | Compara conteo/tamaño/hash entre origen y destino. |
| OPS-010 | P2 | Añadir Traefik labels si se quiere compose autodetectable | Claude | `docker-compose.prod.yml` | Coolify/Traefik enruta backend/frontend sin configuración manual extra. |
| OPS-011 | P1 | `.env` separados: local, PC IA, production | Revisión propia | `.env.*` | No mezclar credenciales/local/producción. |
| OPS-012 | P1 | Script de arranque para PC IA | Revisión propia | `scripts/start-docuintel.ps1` o `.sh` | Arranque controlado de servicios en orden. |

---

# Sprint 4 — Búsqueda, pgvector y futura migración a Qdrant

| ID | Prioridad | Tarea | Origen | Zona afectada | Criterio de terminado |
|---|---|---|---|---|---|
| VEC-001 | P1 | Usar pgvector en SQL, no similitud en Python | Revisión propia | `search_service.py` | Consulta usa `ORDER BY embedding <=> :query_embedding`. |
| VEC-002 | P1 | Crear capa `VectorStore` | Revisión propia | `backend/app/services/vector_store.py` | Backend no depende directamente de pgvector. |
| VEC-003 | P1 | Implementar `PgvectorStore` | Revisión propia | Backend services | Métodos: `upsert_chunks`, `search`, `delete_document`, `rebuild_index`. |
| VEC-004 | P2 | Dejar esqueleto `QdrantStore` opcional | Revisión propia | Backend services | Cambio futuro por `.env VECTOR_STORE=qdrant` preparado. |
| VEC-005 | P1 | Índices PostgreSQL adecuados | Revisión propia | Alembic/migrations | Índices por `budget_scope_id`, `document_id`, `document_type`, `created_at`, embedding. |
| VEC-006 | P1 | Full-text search PostgreSQL | Revisión propia | Search/migrations | Añadir `tsvector`/GIN para búsqueda textual real. |
| VEC-007 | P1 | Búsqueda híbrida real | Revisión propia | `search_service.py` | Combina score textual + vectorial + filtros + recency si aplica. |
| VEC-008 | P1 | Filtro de seguridad dentro de `VectorStore.search()` | Revisión propia | VectorStore | No permite `search()` sin `budget_scope_id` o scope autorizado. |
| VEC-009 | P1 | Marcar embeddings fallback | Claude corregido | Embedding service/DB | `embedding_provider_used`, `needs_reembedding`, `embedding_fallback=true`. |
| VEC-010 | P1 | Job de reindexado de embeddings fallback | Claude | Celery/admin | Recalcula embeddings cuando el servidor real esté disponible. |
| VEC-011 | P2 | Script futuro `backfill_qdrant.py` | Revisión propia | scripts | Migra chunks existentes a Qdrant si se decide cambiar. |
| VEC-012 | P2 | Tests de búsqueda con presupuesto | Revisión propia | Tests backend | Search vectorial nunca devuelve chunks de otro scope. |

---

# Sprint 5 — OCR, planos y documentos grandes

| ID | Prioridad | Tarea | Origen | Zona afectada | Criterio de terminado |
|---|---|---|---|---|---|
| OCR-001 | P1 | Procesar PDFs página por página | Revisión propia | OCR/parser/tasks | Fallar una página no tumba el documento completo. |
| OCR-002 | P1 | Guardar estado OCR por página | Revisión propia | DB models/migrations | `page_status`, `ocr_confidence`, `attempts`, `error_message`, `processing_time_ms`. |
| OCR-003 | P1 | Reprocesar solo páginas fallidas | Revisión propia | Admin/API/tasks | **Hecho 2026-05-21:** endpoint de página crea `reprocess:ocr_page:<pagina>` y actualiza solo esa página si tiene preview. |
| OCR-004 | P1 | Controlar DPI al rasterizar planos/PDF | Revisión propia | OCR/PDF renderer | No generar imágenes gigantes por accidente. |
| OCR-005 | P1 | Detectar planos sin escala o con OCR bajo | Revisión propia | Plan extraction/admin | Quedan en bandeja de revisión. |
| OCR-006 | P1 | Mejorar diagnóstico de documento | Revisión propia | Document quality | Explica por qué está `processed_low_quality` o `needs_review`. |
| OCR-007 | P2 | Edición manual versionada de OCR | Revisión propia | Frontend/admin/backend | Correcciones humanas guardan versión y usuario. |
| OCR-008 | P2 | Historial de reprocesado | Revisión propia | Audit/jobs | Guarda quién reprocesó, cuándo y por qué. |
| OCR-009 | P2 | Fixtures reales para tests OCR | Claude | `tests/fixtures` | Presupuestos, planos, facturas, imágenes y Excel reales/anonimizados. |
| OCR-010 | P2 | Sustituir PDFs performance idénticos | Claude | `tests/performance` | Tests usan documentos variados, no copias idénticas. |
| OCR-011 | P2 | Probar PaddleOCR v3 en rama separada | Claude corregido | `requirements.txt`, OCR engine | Comparativa precisión/velocidad antes de migrar. |
| OCR-012 | P3 | Extracción geométrica avanzada de planos | Revisión propia | Plan service | Extrae medidas desde geometría, no solo OCR textual. |

---

# Sprint 6 — IA, prompts y respuesta verificable

| ID | Prioridad | Tarea | Origen | Zona afectada | Criterio de terminado |
|---|---|---|---|---|---|
| AI-001 | P0 | No responder sin fuentes | Revisión propia | AI agent | Si no hay contexto documental, responde “no hay datos suficientes”. |
| AI-002 | P0 | No mezclar presupuestos aunque el usuario lo pida | Revisión propia | AI/tools/security | Preguntas trampa no cambian de scope. |
| AI-003 | P0 | No inferir importes ocultos | Revisión propia | AI/redaction | Importes redactados no se reconstruyen. |
| AI-004 | P1 | Respuesta obligatoria estructurada | Revisión propia | AI response | Siempre incluye `Respuesta`, `Datos`, `Fuentes`, `Confianza`, `Advertencias`. |
| AI-005 | P1 | Confianza por respuesta | Revisión propia | AI service | Alta/media/baja según OCR, fuentes y coincidencia. |
| AI-006 | P1 | Citas por documento/página/chunk | Revisión propia | AI/front | Cada respuesta enlaza fuentes concretas. |
| AI-007 | P1 | Mejorar selección de tools por idioma/sinónimos | Claude | `backend/app/ai/agent.py` | No depende solo de regex españolas simples. |
| AI-008 | P1 | Fallback seguro cuando no hay match de tool | Claude | AI agent | Usa búsqueda híbrida segura, no tool arbitraria. |
| AI-009 | P1 | Healthcheck de LLM local y embeddings | Claude | `/health`, admin system health | Verifica `/v1/embeddings` y `/v1/chat/completions` o equivalente. |
| AI-010 | P1 | Modo degradado visible | Revisión propia | Backend/frontend | Si IA/embeddings no están disponibles, UI lo muestra claramente. |
| AI-011 | P1 | Tests anti-fuga de IA | Revisión propia | Tests | Preguntas trampa entre presupuestos/importes fallan correctamente. |
| AI-012 | P2 | Sandbox para tools externas | Revisión propia | Integrations v1 | Probar argumentos y fuentes sin generar respuesta final. |

---

# Sprint 7 — Producto y pantallas operativas

| ID | Prioridad | Tarea | Origen | Zona afectada | Criterio de terminado |
|---|---|---|---|---|---|
| UI-001 | P1 | Vista principal “por presupuesto” | Revisión propia | Frontend/backend | Ver documentos, pedidos, facturas, planos y estado de un presupuesto. |
| UI-002 | P1 | Bandeja de documentos pendientes | Revisión propia | Frontend admin | Lista accionable de documentos sin procesar. |
| UI-003 | P1 | Bandeja de OCR bajo | Revisión propia | Frontend admin | Muestra documentos con baja confianza OCR. |
| UI-004 | P1 | Bandeja de planos sin escala | Revisión propia | Frontend plans/admin | Planos que requieren revisión manual. |
| UI-005 | P1 | Presupuestos aceptados sin pedido | Revisión propia | Alerts/admin | Alerta automática accionable. |
| UI-006 | P1 | Pedidos sin presupuesto | Revisión propia | Alerts/admin | Alerta automática accionable. |
| UI-007 | P2 | Duplicados inteligentes | Revisión propia | Documents/admin | Duplicados por hash y por nombre parecido visibles. |
| UI-008 | P2 | Diagnóstico por documento | Revisión propia | Document viewer | Explica errores, calidad OCR y campos faltantes. |
| UI-009 | P2 | Simulador de permisos | Revisión propia | Admin/access | Explica por qué usuario/técnico puede o no ver documento/importes. |
| UI-010 | P2 | Filtros avanzados | Revisión propia | Frontend lists | Filtrar por presupuesto, tipo, estado OCR, fecha, fuente, usuario, importes. |
| UI-011 | P2 | Dashboard ejecutivo | Revisión propia | Frontend dashboard | Procesados, pendientes, errores, volumen, calidad, colas. |
| UI-012 | P2 | Exportación Excel por presupuesto | Revisión propia | Backend/frontend | Exporta documentos/entidades/estado de un presupuesto. |

---

# Sprint 8 — Extracción estructurada y perfiles por proveedor

| ID | Prioridad | Tarea | Origen | Zona afectada | Criterio de terminado |
|---|---|---|---|---|---|
| EXT-001 | P1 | Perfiles por proveedor/formato | Revisión propia | `provider_profiles/*.yaml` | Reglas por proveedor para campos y tablas. |
| EXT-002 | P1 | Extracción avanzada de tablas | Revisión propia | Parser/extraction | Detecta líneas: referencia, descripción, cantidad, precio, total. |
| EXT-003 | P1 | Mejorar relación presupuesto-pedido-factura | Revisión propia | DB/services | Vinculación automática con confianza y revisión humana. |
| EXT-004 | P2 | Normalizar fechas, monedas e importes | Revisión propia | Extraction service | Formato consistente, sin confundir coma/punto. |
| EXT-005 | P2 | Detectar campos críticos faltantes | Revisión propia | Quality service | Presupuesto sin número/cliente/total queda marcado. |
| EXT-006 | P2 | Cola de revisión humana de extracción | Revisión propia | Frontend/admin | Usuario corrige campos clave sin tocar original. |
| EXT-007 | P2 | Versionado de extracción corregida | Revisión propia | DB/audit | Se guarda valor original, corregido, usuario y fecha. |
| EXT-008 | P3 | Modelo ligero para clasificación documental | Revisión propia | ML/classification | Clasifica tipo documental con más precisión que regex. |

---

# Sprint 9 — Refactor y mantenibilidad

| ID | Prioridad | Tarea | Origen | Zona afectada | Criterio de terminado |
|---|---|---|---|---|---|
| REF-001 | P2 | Dividir `backend/app/api/routes/admin.py` | Ambos | Backend routes | Crear módulos: users, alerts, audit, quality, operations, integrations, permissions. |
| REF-002 | P2 | Dividir `frontend/src/pages/AdminPage.tsx` | Ambos | Frontend | Crear componentes por panel. |
| REF-003 | P2 | Normalizar errores API | Revisión propia | Backend | Respuestas de error consistentes para frontend. |
| REF-004 | P2 | Separar servicios backend grandes | Revisión propia | Backend services | OCR, búsqueda, permisos, IA, documentos sin responsabilidades mezcladas. |
| REF-005 | P2 | Añadir Ruff/Black | Revisión propia | Backend tooling | `ruff check` y formato en CI. |
| REF-006 | P2 | Añadir ESLint/Prettier estricto | Revisión propia | Frontend tooling | `npm run lint` limpio. |
| REF-007 | P2 | CI básico | Revisión propia | GitHub Actions/Codex | Ejecuta tests backend/frontend antes de desplegar. |
| REF-008 | P3 | Documentar arquitectura real actual | Revisión propia | README/docs | Eliminar confusión Qdrant vs pgvector si se mantiene pgvector. |
| REF-009 | P3 | Crear ADRs de decisiones técnicas | Revisión propia | `docs/adr` | ADR para pgvector, Qdrant futuro, OCR, IA local, permisos. |

---

# Sprint 10 — Tests mínimos obligatorios

| ID | Prioridad | Tarea | Origen | Zona afectada | Criterio de terminado |
|---|---|---|---|---|---|
| TEST-001 | P0 | Test: usuario sin permiso no ve presupuesto ajeno | Revisión propia | Tests security | Falla con 403 o resultado vacío. |
| TEST-002 | P0 | Test: API externa no sube a `budget_code` no autorizado | Revisión propia | Tests integrations | Devuelve 403. |
| TEST-003 | P0 | Test: IA no recibe chunks fuera de scope | Revisión propia | Tests AI | Verifica chunk IDs enviados. |
| TEST-004 | P0 | Test: importes redactados antes de IA | Revisión propia | Tests redaction | Contexto enviado tiene `[IMPORTE OCULTO]`. |
| TEST-005 | P1 | Test: PDF gigante se rechaza/controla | Revisión propia | Tests file security | No entra a OCR sin control. |
| TEST-006 | P1 | Test: imagen gigante se rechaza/controla | Revisión propia | Tests file security | No tumba worker. |
| TEST-007 | P1 | Test: extensión falsa se bloquea | Revisión propia | Tests file security | `.pdf` con binario ejecutable rechazado. |
| TEST-008 | P1 | Test: watcher detecta archivo modificado | Claude | Tests watcher | Cambio de hash reencola/versiona. |
| TEST-009 | P1 | Test: enrutado Celery por tipo | Claude corregido | Tests workers | PDF a `ocr_heavy`, Excel a `text_fast`. |
| TEST-010 | P1 | Test: embeddings fallback quedan marcados | Claude | Tests embeddings | Documento queda `needs_reembedding=true`. |
| TEST-011 | P1 | Test: pgvector search filtra por presupuesto | Revisión propia | Tests search | Nunca devuelve chunks de otro scope. |
| TEST-012 | P2 | Tests performance con fixtures reales | Claude | Tests performance | Usa documentos variados, no duplicados idénticos. |

---

# Orden recomendado de ejecución con Codex

## Semana 1 — Cierre de riesgos reales

- [ ] SEC-001 Cookie segura en producción.
- [ ] SEC-003 Rate limit login.
- [ ] SEC-004 Validar permisos en upload externo por `budget_code`.
- [ ] SEC-005 Filtro obligatorio por `budget_scope_id`.
- [ ] SEC-006 Tests anti-fuga entre presupuestos.
- [ ] SEC-007 Redacción obligatoria de importes.
- [ ] FILE-001 Límite upload HTTP.
- [ ] FILE-002 Límite páginas PDF.
- [ ] FILE-005 Validación MIME real.
- [ ] FILE-006 Bloquear/arreglar `.doc/.docx`.
- [ ] OPS-001/002 Backup y restore Linux.

## Semana 2 — Robustez técnica

- [ ] CEL-001 Workers separados.
- [ ] CEL-005 Watcher detecta modificaciones.
- [ ] OPS-007 Script importación masiva.
- [ ] AI-009 Healthcheck LLM/embeddings.
- [ ] VEC-001 pgvector en SQL.
- [ ] VEC-002 Crear `VectorStore`.
- [ ] VEC-009 Marcar embedding fallback.
- [ ] OCR-001 OCR por página.
- [ ] OCR-002 Estado OCR por página.

## Semana 3 — Producto usable

- [ ] UI-001 Vista por presupuesto.
- [ ] UI-002 Bandeja pendientes.
- [ ] UI-003 Bandeja OCR bajo.
- [ ] UI-004 Planos sin escala.
- [ ] UI-005 Presupuestos aceptados sin pedido.
- [ ] UI-006 Pedidos sin presupuesto.
- [ ] UI-008 Diagnóstico por documento.
- [ ] AI-004 Respuesta IA estructurada.
- [ ] AI-006 Fuentes por chunk/página.

## Semana 4 — Calidad y mantenibilidad

- [ ] EXT-001 Perfiles por proveedor.
- [ ] EXT-002 Extracción avanzada de tablas.
- [ ] REF-001 Dividir `admin.py`.
- [ ] REF-002 Dividir `AdminPage.tsx`.
- [ ] TEST-012 Fixtures reales.
- [ ] OCR-011 Probar PaddleOCR v3 en rama separada.
- [ ] REF-008 Documentar arquitectura real pgvector/Qdrant futuro.

---

# Prompt recomendado para Codex

```text
Analiza el proyecto Docu-Intel y aplica únicamente las tareas del Sprint 0 y Sprint 1 de este backlog.

Reglas:
- No cambies arquitectura principal sin justificarlo.
- Mantén PostgreSQL + pgvector.
- No introduzcas Qdrant todavía.
- Toda búsqueda documental o IA debe exigir budget_scope_id autorizado.
- Añade tests para cada cambio de seguridad.
- No elimines compatibilidad sin indicarlo.
- Si un cambio afecta Docker/.env, actualiza .env.example y documentación.
- Entrega un resumen de archivos modificados y comandos de prueba.
```

---

# Decisiones técnicas recomendadas

## Mantener pgvector ahora

- Menos servicios.
- Backup más simple.
- Mejor integración con permisos y documentos.
- Qdrant solo si hay millones de chunks o latencia alta.

## Preparar Qdrant sin migrar aún

- Crear `VectorStore`.
- Guardar payload limpio por chunk.
- Mantener PostgreSQL como verdad principal.
- Qdrant, si llega, será índice secundario.

## No priorizar PaddleOCR v3 antes que seguridad

Actualizar PaddleOCR puede mejorar precisión, pero no arregla los riesgos principales. Primero seguridad, aislamiento, backups y límites.

## No confiar en IA sin fuentes

La IA debe actuar como capa de respuesta sobre datos recuperados, no como fuente de verdad.

---

# Checklist final de producción mínima

La app no debería considerarse lista hasta cumplir esto:

- [ ] Login protegido contra fuerza bruta.
- [ ] Cookies seguras en producción.
- [ ] API externa no puede cambiar de presupuesto sin permiso.
- [ ] Toda búsqueda usa `budget_scope_id`.
- [ ] La IA no recibe datos fuera del scope.
- [ ] Importes se redactan antes de enviar contexto a IA.
- [ ] Uploads tienen límite de tamaño.
- [ ] PDFs tienen límite de páginas.
- [ ] Imágenes tienen límite de píxeles.
- [ ] MIME/firma validado.
- [ ] `.doc/.docx` bloqueado o parser real.
- [ ] Backup Linux funcionando.
- [ ] Restore probado.
- [ ] Redis protegido en producción.
- [ ] Worker OCR separado.
- [ ] Watcher detecta modificaciones.
- [ ] pgvector se usa en SQL.
- [ ] Healthcheck incluye IA y embeddings.
- [ ] Tests anti-fuga entre presupuestos pasan.
- [ ] Tests de redacción de importes pasan.
- [ ] Documentación de operación actualizada.
