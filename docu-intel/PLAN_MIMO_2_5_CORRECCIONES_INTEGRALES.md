# Plan maestro para Mimo 2.5: estabilización, proyectos, chat e imágenes

> Documento de ejecución para un modelo con menos contexto del repositorio.
> Debe leerse completo antes de modificar código, pero debe ejecutarse **una sola fase cada vez**.

## 1. Objetivo final

Convertir Docu-Intel en una aplicación capaz de importar, sin mover ni renombrar, la estructura fija de carpetas de `D:\TEST2025\2025`, relacionar cada documento con año, marca, hotel, proyecto y presupuesto, y permitir que un gestor consulte desde el chat:

- De qué trata un proyecto o presupuesto.
- Qué documentos lo forman.
- Qué se presupuestó, pidió, entregó y facturó.
- Productos, cantidades, precios y diferencias económicas.
- Correos, participantes, comerciales y responsables.
- Problemas, decisiones, instalaciones, incidencias y soluciones.
- Imágenes, planos, croquis, tejidos, pagos y fotografías de resultado.

Cada respuesta debe estar limitada por permisos y respaldada por documentos, páginas, imágenes o correos concretos.

## 2. Restricciones que no se pueden romper

1. **No mover, renombrar, editar ni borrar nada dentro de `D:\TEST2025\2025`.**
2. El montaje de esa carpeta debe ser de solo lectura (`:ro`).
3. La jerarquía real es fija y tiene dos variantes válidas:

   ```text
   2025/Marca/Presupuesto XXXXX/Tipo/archivo
   2025/Marca/Hotel/Presupuesto XXXXX/Tipo/archivo
   ```

4. Una misma marca puede mezclar presupuestos directos y hoteles.
5. No deducir que dos documentos pertenecen al mismo proyecto solo por compartir cliente o proveedor.
6. No usar el nombre hash almacenado para clasificar; conservar siempre nombre y ruta originales.
7. No inventar medidas, precios, fechas, participantes, referencias ni estados.
8. No mostrar IBAN, cuentas, NIF/CIF, importes o datos sensibles a usuarios sin permiso.
9. No romper las interfaces públicas `BaseOCREngine`, `embed_many`, `embed_query_text` ni `search_*`.
10. Mantener la política de no usar embeddings hash como fallback silencioso.
11. Todo cambio de esquema requiere migración Alembic reversible y prueba de upgrade.
12. Todo comportamiento nuevo requiere pruebas.
13. No sobrescribir cambios no relacionados que ya estén en el worktree.
14. No comenzar una fase si la anterior no cumple sus criterios de aceptación.

## 3. Estado confirmado antes de empezar

### 3.1 Corpus

- `D:\TEST2025\2025`: 31.323 archivos, aproximadamente 22,73 GB.
- 456 carpetas principales.
- 2.966 carpetas `Presupuesto XXXXX`, todas con código distinto en 2025.
- 2.062 presupuestos directamente bajo la marca.
- 904 presupuestos bajo una carpeta intermedia de hotel.
- Todos los archivos están dentro de un presupuesto y una categoría documental.
- 6.219 imágenes: producto, instalación, tejido, croquis, plano, pago, factura fotografiada, incidencia, render y otros.

### 3.2 Fallos críticos actuales

- `backend/app/models/professional.py` tiene un `SyntaxError`; un backend nuevo no puede arrancar.
- El frontend no compila por imports y query keys ausentes.
- PostgreSQL activo contiene cero documentos.
- La mayoría de workers, watcher y scheduler están detenidos.
- Docker no monta actualmente `D:\TEST2025\2025`.
- El contenedor de migración conserva un fallo antiguo por columna `project_phase` duplicada.
- Las pruebas no pueden recogerse mientras exista el `SyntaxError`.
- `EXACT_SEARCH` existe en `_registry.py`, pero no está exportado correctamente.

### 3.3 Fallos funcionales confirmados

- Todas las conversaciones del frontend comparten un único `session_id`.
- Las conversaciones guardadas sin `messages` pueden romperse después de recargar.
- La búsqueda exacta puede incorporar documentos antes de filtrar permisos.
- La deduplicación por SHA devuelve el primer documento procesado y pierde la segunda ruta/presupuesto.
- El fallback de ruta puede crear presupuestos falsos llamados `PDF`, `CORREOS`, etc.
- El grafo relaciona la carpeta inmediata, no todo el `budget_scope_id`.
- No existen marca, hotel, proyecto, contactos ni conversaciones estructuradas.
- Las líneas de factura se extraen, pero no se persisten.
- Los adjuntos `.msg` solo se enumeran; no se extraen como documentos relacionados.
- El chat no tiene contexto de proyecto, marca ni hotel.

### 3.4 Fallos visuales confirmados

- El router recibe con frecuencia el nombre hash y `2025` como pista de carpeta.
- `clip_classifier.py` no usa CLIP; usa heurísticas OpenCV.
- Fotos de instalación y tejidos se clasifican a menudo como planos o documentos.
- Imágenes de pago e incidencias pueden caer en `interior_design`.
- `interior_design` omite OCR aunque pueda haber texto, medidas o etiquetas.
- Toda salida visual se guarda como bloque `table` con confianza fija 0.85.
- Las imágenes grandes se reducen completas a 1.024 px para visión.
- No hay embedding visual nativo ni conocimiento visual estructurado.
- Las descripciones visuales pueden recalcularse durante el chat, generando latencia e inconsistencias.

## 4. Resultado técnico esperado

```text
Marca
└── Hotel opcional
    └── Proyecto
        ├── uno o varios presupuestos
        ├── apariciones/rutas documentales
        ├── presupuestos, pedidos, albaranes y facturas
        ├── líneas de producto
        ├── correos e hilos
        ├── participantes internos y externos
        ├── imágenes y conocimiento visual
        ├── incidencias, decisiones y tareas
        └── cronología y dossier consultable
```

Separar obligatoriamente:

```text
Archivo físico (SHA256)
!= Aparición del archivo en una ruta
!= Relación de esa aparición con presupuesto/proyecto
```

Esto permite que el mismo archivo físico aparezca en varios presupuestos sin duplicar bytes y sin perder relaciones.

## 5. Forma obligatoria de trabajar para Mimo 2.5

Al iniciar cada fase:

1. Ejecutar `git status --short` y `git diff --check`.
2. Leer `AGENTS.md` completo.
3. Leer todos los archivos nombrados en esa fase antes de editarlos.
4. Anotar qué cambios existentes no pertenecen a la fase y preservarlos.
5. Ejecutar las pruebas base indicadas.
6. Implementar el mínimo cambio necesario.
7. Añadir pruebas antes de considerar terminada la fase.
8. Ejecutar compilación, pruebas focalizadas y comprobación de migraciones.
9. Detenerse y entregar un resumen; no iniciar automáticamente la fase siguiente.

Formato de entrega de cada fase:

```text
Fase ejecutada:
Archivos modificados:
Migraciones creadas:
Pruebas ejecutadas y resultado:
Riesgos pendientes:
Datos que requieren backfill:
Confirmación de que D:\TEST2025\2025 no fue modificado:
```

## FASE 0 — Recuperar un repositorio compilable

### Objetivo

Conseguir que backend y frontend compilen sin eliminar trabajo válido en curso.

### Archivos mínimos a revisar

- `backend/app/models/professional.py`
- `backend/app/models/__init__.py`
- `frontend/src/hooks/useAuth.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/lib/queryKeys.ts`
- `frontend/src/pages/InvoicesPage.tsx`
- `frontend/src/pages/plano/usePlanOverlays.ts`
- `frontend/src/api/core.ts`

### Tareas

1. Reparar los paréntesis y clases rotas en `professional.py`.
2. Restaurar `WorkItem.updated_at`, la relación `comments` y `WorkItemComment` si fueron eliminados accidentalmente.
3. Mantener las nuevas clases de obra solo si están completas, importadas y respaldadas por migración.
4. Verificar todas las exportaciones de `models/__init__.py`.
5. Corregir imports frontend sin crear APIs ficticias.
6. Añadir las query keys realmente utilizadas o modificar los consumidores para usar las existentes.
7. No silenciar TypeScript con `any`, `@ts-ignore` o casts globales.

### Verificación obligatoria

```powershell
python -m compileall -q backend/app
python -m pytest -q backend/tests/test_app_imports.py
cd frontend
npm run build
npm run lint
```

### Criterio de aceptación

- `import app.main` funciona en host y contenedor.
- `npm run build` termina con código 0.
- No quedan clases ORM a medio definir.

### Punto de parada

Si no compila, no tocar Docker, base de datos, chat ni imágenes.

## FASE 1 — Arranque, migraciones y servicios

### Objetivo

Hacer que un despliegue limpio arranque de forma reproducible y reporte su estado real.

### Archivos

- `docker-compose.yml`
- `.env.example` o plantilla equivalente; no publicar secretos de `.env`
- `backend/alembic/versions/*`
- `backend/app/main.py`
- `backend/app/api/routes/health.py`
- `backend/docker-entrypoint.sh`

### Tareas

1. No cambiar migraciones históricas a ciegas.
2. Comparar `alembic current`, `alembic heads` y columnas reales.
3. Si la base está ya en `0047`, recrear el contenedor `migrate` y confirmar que `upgrade head` es no-op y sale 0.
4. Si existe deriva real, documentarla y crear una migración de reconciliación nueva; no usar `stamp` sin evidencia.
5. Cambiar el healthcheck Docker de `/health` a `/healthz`.
6. Añadir readiness de workers/watcher en el panel de sistema, sin hacer que el backend dependa de GPU para responder HTTP.
7. Corregir permisos de `data/files`: los workers no deben recibir `Permission denied` al renderizar páginas.
8. Revisar el uso de `user:` y el `chown` del entrypoint; un proceso no-root no puede corregir archivos root si el entrypoint ya corre como no-root.
9. Corregir GPU 1: si `NVIDIA_VISIBLE_DEVICES=1` expone una sola GPU dentro del contenedor, su índice interno es 0. No combinarlo con un índice local inválido.
10. Arrancar watcher, fast worker, maintenance, scheduler y los workers OCR necesarios.

### Verificación

```powershell
docker compose config
docker compose run --rm migrate
docker compose up -d
docker compose ps -a
docker compose exec -T backend python -c "import app.main"
docker compose exec -T postgres psql -U app -d docuintel -c "select version_num from alembic_version"
```

### Criterio de aceptación

- Migración sale 0.
- Backend, Redis y PostgreSQL están listos.
- Workers necesarios responden a `celery inspect ping`.
- Una imagen y un PDF de prueba pueden escribir sus derivados en `data/files`.
- GPU 0 y GPU 1 procesan una tarea cada una sin error de índice.

## FASE 2 — Montaje seguro de la estructura fija

### Objetivo

Leer `D:\TEST2025\2025` directamente sin copiar, modificar ni renombrar el corpus.

### Diseño

Introducir una variable de entorno, por ejemplo:

```text
SOURCE_CORPUS_DIR=D:/TEST2025/2025
```

Montarla en una ruta separada y de solo lectura:

```yaml
- ${SOURCE_CORPUS_DIR}:/app/source/2025:ro
```

No superponerla con un directorio que necesite escritura.

### Tareas

1. Aplicar el montaje a watcher y a cualquier proceso que necesite abrir el original.
2. Mantener `data/files` como almacenamiento derivado escribible.
3. Añadir `source_root` configurable al watcher.
4. Comprobar que el watcher no ejecuta `unlink`, `rename`, `move`, `chmod` o escritura sobre `source_root`.
5. Añadir prueba con un árbol temporal montado conceptualmente como solo lectura.
6. Registrar el año `2025` como metadato, no como tipo documental.

### Criterio de aceptación

- Dentro del watcher existen exactamente 31.323 archivos visibles.
- El corpus original conserva hashes, fechas y nombres antes/después de una prueba.
- Todos los derivados se crean fuera del corpus.

## FASE 3 — Modelo jerárquico y resolvedor de pertenencia

### Objetivo

Representar marca, hotel, proyecto, presupuesto y múltiples apariciones del mismo archivo.

### Modelos recomendados

Los nombres pueden adaptarse a las convenciones existentes, pero deben cubrir estos contratos:

```text
Brand
  id, canonical_name, normalized_name

Hotel
  id, brand_id nullable, canonical_name, normalized_name

Project
  id, year, brand_id, hotel_id nullable, name, status,
  primary_budget_scope_id nullable, description, manager_user_id nullable

DocumentOccurrence
  id, document_id, source_path, source_root, year,
  brand_id, hotel_id nullable, budget_scope_id,
  project_id nullable, category, original_filename,
  is_primary, first_seen_at, last_seen_at

DocumentBudgetLink
  id, document_id, occurrence_id nullable, budget_scope_id,
  source(folder|content|filename|relation|manual),
  extracted_code nullable, confidence, status,
  evidence_json, reviewed_by_id nullable
```

### Compatibilidad

- Mantener temporalmente `Document.budget_scope_id` como enlace primario legado.
- No usarlo como única relación después de esta fase.
- Revisar la unicidad global de `BudgetScope.budget_code`; preparar una identidad compuesta que soporte año y contexto sin romper datos actuales.

### Resolvedor de ruta

Crear un servicio único, por ejemplo `services/project_path_resolver.py`.

Algoritmo obligatorio:

1. Normalizar `/` y `\` sin cambiar el valor original persistido.
2. Encontrar un segmento que coincida estrictamente con `^Presupuesto\s+([A-Za-z0-9._/-]+)$`.
3. Rechazar como código nombres genéricos: `PDF`, `CORREOS`, `EXCEL`, `IMAGENES`, `PLANOS`, `WORD`, `OTROS`, `ZIP`, año o filename.
4. El segmento posterior al presupuesto es categoría documental.
5. El primer segmento después del año es marca/grupo.
6. Si existe un segmento entre marca y presupuesto, es hotel/establecimiento provisional.
7. Si el presupuesto está directamente bajo marca, `hotel_id = null`; no inventar hotel.
8. Conservar alias exactos de ruta; la canonicalización humana puede venir después.

### Conciliación carpeta-contenido

Persistir por separado:

```text
folder_budget_code
document_budget_code
resolved_budget_code
association_status
```

Reglas:

- Iguales: `verified`.
- Solo carpeta: `folder_only`, válido pero no confirmado internamente.
- Solo contenido: `content_only`, enlazar si el scope existe o crear revisión.
- Distintos: `conflict`; no mover ni reasignar silenciosamente.
- Una referencia explícita a otro presupuesto puede crear un enlace secundario, no sustituir el enlace de carpeta.

### Pruebas mínimas

- Ruta directa marca/presupuesto.
- Ruta marca/hotel/presupuesto.
- Marca con mezcla de ambas.
- Nombres con espacios, acentos y paréntesis.
- Ruta sin presupuesto.
- Conflicto carpeta-contenido.
- Mismo hash en dos presupuestos.
- Repetición futura del código en otro año.

### Criterio de aceptación

- Cada uno de los 31.323 archivos produce una aparición con marca, presupuesto y categoría.
- Los 2.966 presupuestos quedan representados sin falsos scopes `PDF` o `CORREOS`.
- El mismo SHA puede tener varias apariciones y enlaces.

## FASE 4 — Deduplicación correcta y carga masiva

### Objetivo

Deduplicar bytes sin deduplicar relaciones de negocio.

### Archivos

- `backend/app/services/document_registration_service.py`
- `backend/app/ingestion/watcher.py`
- `backend/app/ingestion/scanner.py`
- `backend/app/services/file_storage.py`
- `frontend/src/pages/documents/DocumentsPage.tsx`
- `frontend/src/api/documents.ts`
- `frontend/nginx.conf`

### Tareas

1. Si ya existe el SHA, reutilizar `stored_filename`, pero crear/actualizar `DocumentOccurrence` para la nueva ruta.
2. No devolver el documento existente sin registrar el nuevo presupuesto.
3. Añadir índice único de aparición por `source_root + source_path`, no solo por SHA.
4. Detectar modificaciones de una ruta como nueva versión, preservando historial.
5. Para imágenes, calcular opcionalmente `perceptual_hash` para detectar copias redimensionadas; nunca usarlo para fusionar relaciones automáticamente.
6. El selector de carpeta debe conservar `webkitRelativePath`.
7. El drag-and-drop debe recorrer directorios mediante File System Access API o impedir claramente la carga de carpetas si no puede conservar rutas.
8. No enviar 31.323 archivos/22,73 GB en un solo multipart.
9. Implementar lotes pequeños reanudables, con identificador de sesión, progreso y reintento por archivo.
10. Para el corpus fijo, preferir watcher directo antes que upload HTTP.

### Criterio de aceptación

- Dos rutas con mismo SHA aparecen en ambos presupuestos.
- Reanudar un lote no duplica apariciones.
- Un fallo de archivo no invalida el resto del lote.
- La UI muestra procesados, duplicados físicos, fallidos y pendientes.

## FASE 5 — Clasificación y conocimiento de imágenes

### Objetivo

Tratar correctamente la diversidad visual sin perder texto ni inventar datos.

### Error que se debe eliminar

No llamar `classify_content` con el path hash como única identidad. La entrada debe incluir:

```text
stored_path
original_filename
source_path completo
category de carpeta
budget_scope_id
```

### Taxonomía multietiqueta

Una imagen puede tener más de una clase:

```text
foto_producto
foto_instalacion
muestra_material
croquis_medicion
plano_tecnico
documento_fotografiado
comprobante_pago
incidencia
render
captura_pantalla
logo_grafico
desconocido
```

### Estrategia de procesamiento

1. **Documento, pago o captura:** OCR primero, visión después; extraer campos estructurados y datos sensibles.
2. **Croquis o plano:** OCR + visión por regiones/tiles; conservar geometría y cotas.
3. **Producto, tejido o instalación:** visión descriptiva + embedding visual + OCR ligero para etiquetas.
4. **Incidencia:** visión para objeto, daño, zona y severidad; nunca afirmar causa o responsabilidad sin evidencia.
5. **Imagen desconocida:** ejecutar OCR ligero y descripción genérica; no saltar ambos.

### Cambios obligatorios

- Renombrar o documentar `clip_classifier.py`: hoy es heurístico OpenCV, no CLIP.
- No considerar su resultado verdad semántica.
- Usar filename/ruta antes de la pista amplia `IMAGENES`.
- No hacer que `IMAGENES` fuerce `interior_design` antes de evaluar pago, plano, tejido o croquis.
- Manejar rutas Unicode con lectura `np.fromfile + cv2.imdecode` o Pillow, no depender solo de `cv2.imread` en Windows.
- No guardar todas las descripciones como `block_type="table"`.
- No asignar confianza fija 0.85 a toda salida VLM.
- Guardar confianza por hecho y `model_version`.
- Marcar medidas inferidas sin unidad como `unit_inferred=true` y requerir revisión.
- Aplicar tiling a imágenes grandes; una reducción global a 1.024 px no sirve para texto pequeño.
- La imagen de 168 MP debe generar un derivado seguro o quedar en revisión, no tumbar la tarea.

### Modelo recomendado

```text
ImageAnalysis
  document_id, occurrence_id, labels_json, description,
  visible_text, objects_json, materials_json, colors_json,
  measurements_json, product_refs_json, room_or_zone,
  installation_state, issue_json, sensitive_data_json,
  visual_embedding, perceptual_hash,
  model_name, model_version, confidence, needs_review
```

### Seguridad visual

- Detectar y etiquetar IBAN, cuentas, NIF/CIF, datos de pago y personas.
- Redactar esos datos según permisos antes de enviarlos al chat.
- No incluir texto bancario completo en embeddings accesibles a usuarios restringidos.

### Evaluación obligatoria

Crear un conjunto dorado revisado manualmente con al menos:

- 25 fotos de producto/instalación.
- 25 tejidos/materiales.
- 25 croquis/mediciones.
- 20 planos.
- 20 pagos/documentos fotografiados.
- 20 incidencias.

Medir por separado clasificación, OCR, medidas, referencias y descripción. No aceptar solo una métrica global.

### Criterio de aceptación

- Ningún pago dorado queda como foto de producto.
- Ningún tejido dorado queda como plano con alta confianza.
- Medidas dudosas se marcan, no se presentan como confirmadas.
- El chat puede encontrar imágenes por objeto, material, color, incidencia y estado de instalación.

## FASE 6 — Documentos comerciales y productos

### Objetivo

Construir una cadena económica completa por proyecto.

### Tareas

1. Crear `InvoiceLine` y persistir las líneas ya devueltas por `InvoiceExtraction`.
2. Relacionar albaranes con pedido/presupuesto cuando exista evidencia.
3. Usar `DocumentBudgetLink` y `Project` para resolver relaciones antes que búsquedas globales.
4. Cuando números de pedido puedan repetirse, limitar la resolución por proyecto, presupuesto, proveedor, marca/hotel o fecha.
5. No usar `.limit(1)` global sin orden y sin ámbito.
6. Crear conciliación por línea:

   ```text
   presupuestado -> pedido -> entregado -> facturado
   ```

7. Conservar descripción, referencia, cantidad, unidad, precio unitario, total, moneda y fuente.
8. Distinguir importes sin IVA, IVA y total.

### Consultas de aceptación

- Productos de un proyecto.
- Diferencia entre presupuesto y pedido.
- Entregado pero no facturado.
- Facturado sin pedido.
- Total presupuestado, pedido y facturado con fuentes.

## FASE 7 — Correos, contactos, participantes e incidencias

### Objetivo

Convertir `.msg` en conversaciones consultables sin perder el documento original.

### Modelos recomendados

```text
Organization
Contact
CommunicationThread
CommunicationMessage
CommunicationParticipant
AttachmentLink
ProjectParticipant
ProjectEvent
ProjectIssue
```

### Tareas

1. Persistir asunto, remitente, destinatarios, CC, fecha y Message-ID cuando exista.
2. Normalizar email sin perder nombre visible original.
3. Reconstruir hilos mediante headers y heurísticas conservadoras de asunto/participantes.
4. Extraer adjuntos de manera segura a almacenamiento derivado.
5. Registrar cada adjunto como documento/aparición enlazado al mensaje y presupuesto.
6. Evitar duplicar un adjunto que ya existe físicamente, pero mantener `AttachmentLink`.
7. No truncar permanentemente el cuerpo a 20.000 caracteres; guardar cuerpo completo saneado y generar una vista resumida.
8. Crear roles de proyecto: gestor interno, comercial interno, comercial externo, cliente, proveedor, arquitecto, instalador, técnico y otros.
9. No inferir definitivamente el rol por dominio de correo; guardar candidato y confianza hasta validación.
10. Extraer decisiones, compromisos, problemas y resoluciones como eventos con fuente exacta.

### Criterio de aceptación

- El chat responde quién participó y en qué mensajes aparece.
- Puede resumir un hilo cronológicamente.
- Cada decisión/problema enlaza al correo concreto.
- Los adjuntos son consultables sin duplicar bytes.

## FASE 8 — Dossier y herramientas de proyecto

### Objetivo

Crear una capa de consulta determinista antes del LLM.

### Herramientas internas mínimas

```text
resolve_project
get_project_dossier
list_project_documents
get_project_financials
get_project_products
get_project_people
get_project_communications
get_project_issues
get_project_timeline
search_project_images
```

### Reglas

- Resolver primero por ID/código exacto.
- Si el usuario nombra presupuesto, usar sus links y proyecto.
- Si nombra hotel, listar/proponer proyectos antes de mezclar todos.
- Si hay ambigüedad entre marca y hotel, pedir concreción o presentar opciones.
- El dossier debe reunir todas las categorías por `budget_scope_id/project_id`, no solo la carpeta inmediata `PDF` o `CORREOS`.
- Relaciones `same_client` y `same_supplier` son sugerencias débiles, nunca pertenencia de proyecto.
- Limitar volumen con resúmenes estructurados, pero permitir drill-down con fuentes.

### Criterio de aceptación

Un dossier contiene descripción, documentos, economía, productos, personas, comunicaciones, imágenes, problemas y cronología con indicadores de datos faltantes.

## FASE 9 — Chat por conversación y proyecto

### Objetivo

Hacer que cada conversación tenga contexto independiente y persistente.

### Cambios

1. Usar el `Conversation.id` como `session_id` estable.
2. Nueva conversación = nuevo `session_id`.
3. Cambiar conversación = cambiar contexto, sin heredar el anterior.
4. Persistir conversaciones y mensajes en backend o hidratar correctamente desde `ChatSession/ChatMessage`.
5. No cargar objetos metadata-only como si contuvieran `messages`.
6. Borrar una conversación debe definir claramente si borra o archiva su sesión backend.
7. Añadir a `ActiveContext`:

   ```text
   current_project_id
   current_project_name
   current_brand_id/name
   current_hotel_id/name
   current_budget_scope_id
   ```

8. El contexto principal debe ser proyecto/presupuesto, no la subcarpeta inmediata.
9. Añadir selector de proyecto opcional en el chat.
10. Añadir sugerencias como “documentos”, “productos”, “facturación”, “personas”, “correos”, “incidencias” e “imágenes”.

### Reparaciones obligatorias

- Exportar `EXACT_SEARCH` desde el módulo público de métricas o importar explícitamente desde el lugar correcto.
- Aplicar `access_scope` a los resultados exactos **antes** de construir `ContextItem` o `resolved_document`.
- Añadir prueba que demuestre que un usuario restringido no ve documento, path, texto ni entidades de otro ámbito.
- No recalcular visión durante cada pregunta si ya existe `ImageAnalysis` vigente.

### Pruebas conversacionales

```text
Conversación A: presupuesto 252536 -> "¿y las facturas?"
Conversación B: presupuesto 250922 -> "¿y las facturas?"
```

Las respuestas no deben cruzarse.

Probar también:

- Recarga de página y nuevo envío.
- Dos pestañas con sesiones distintas.
- Cambio entre proyectos.
- Pregunta ambigua de hotel con varios presupuestos.
- Pregunta sobre imagen, incidencia y participante.

## FASE 10 — Permisos y datos sensibles

### Objetivo

Aplicar autorización antes de recuperar datos, no solo redactarlos después.

### Tareas

1. Toda herramienta debe recibir `AccessScope` o devolver IDs filtrados por una capa común.
2. Filtrar exact search, filename search, dossier, relaciones, imágenes y comunicaciones.
3. Redactar importes para quien no pueda ver precios.
4. Añadir redacción específica para IBAN, cuentas bancarias, NIF/CIF, email y teléfono según política.
5. Evitar filtrar rutas completas del servidor a usuarios restringidos.
6. Aplicar permisos a embeddings y BM25; no recuperar primero y redactar después si el documento no es visible.
7. Registrar auditoría de consultas sensibles sin guardar secretos completos en logs.

### Criterio de aceptación

Matriz de tests para admin, gestor, operario y auditor sobre proyecto permitido y no permitido.

## FASE 11 — Backfill del corpus y control de calidad

### Objetivo

Poblar los nuevos modelos sin reprocesar indiscriminadamente 22,73 GB.

### Orden de backfill

1. Resolver rutas y crear marcas/hoteles/scopes/proyectos/apariciones sin OCR.
2. Enlazar documentos existentes por SHA/ruta.
3. Reconciliar números de presupuesto ya extraídos.
4. Reprocesar primero documentos sin texto o con errores.
5. Extraer líneas de factura pendientes.
6. Procesar correos y adjuntos.
7. Analizar imágenes por lotes controlados.
8. Crear embeddings textuales/visuales al final.

### Requisitos operativos

- Comando reanudable con cursor/checkpoint.
- `--dry-run` obligatorio.
- Límites por lote.
- Métricas de procesados, omitidos, fallidos, conflictos y pendientes.
- Nunca aprobar automáticamente datos conflictivos.
- Poder repetir el comando sin duplicar filas.

### Validaciones del corpus

Esperados inicialmente:

```text
marcas/grupos de primer nivel: 456
presupuestos 2025: 2.966
apariciones documentales: 31.323
imágenes: 6.219
archivos fuera de presupuesto: 0
presupuestos vacíos: 0
```

Las diferencias deben producir un informe, no corregirse silenciosamente.

## FASE 12 — Pruebas E2E, observabilidad y entrega

### Escenario dorado E2E

Elegir varios presupuestos reales con:

- Excel de presupuesto.
- PDF.
- Pedido.
- Factura/albarán.
- Correos.
- Imágenes de producto o instalación.
- Croquis o incidencia cuando exista.

Preguntas mínimas:

```text
Explícame el proyecto 252536.
¿Qué documentos lo forman?
¿Qué productos y precios contiene?
¿Qué se pidió, entregó y facturó?
¿Qué queda pendiente?
¿Quién intervino por nuestra empresa y por la otra?
Resume las conversaciones cronológicamente.
¿Qué problemas hubo y cómo se resolvieron?
¿Qué muestran las imágenes?
Enséñame las incidencias y las fotos de resultado.
```

### Métricas mínimas

- Archivos descubiertos y apariciones creadas.
- Documentos por presupuesto/proyecto.
- Conflictos carpeta-contenido.
- Errores por parser y tipo.
- Precisión del clasificador visual dorado.
- Imágenes sin OCR ni descripción.
- Datos visuales pendientes de revisión.
- Respuestas sin fuente.
- Intentos de acceso denegados.
- Latencia del dossier y del chat.
- Workers activos, colas y tareas estancadas.

### Gate final

```powershell
python -m compileall -q backend/app
python -m pytest -q backend/tests
cd frontend
npm run build
npm run test
npm run lint
docker compose config
docker compose run --rm migrate
```

Además:

- Restaurar una copia de backup en entorno temporal y ejecutar migraciones.
- Ejecutar el escenario dorado con permisos diferentes.
- Verificar que el corpus original no cambió.
- Documentar rollback y backup antes de producción.

## 6. Orden estricto de commits sugerido

```text
M25-00-stabilize-build
M25-01-runtime-migrations-health
M25-02-readonly-source-mount
M25-03-project-path-model
M25-04-occurrence-aware-dedup
M25-05-image-knowledge
M25-06-commercial-chain
M25-07-email-participants
M25-08-project-dossier-tools
M25-09-chat-project-sessions
M25-10-access-redaction
M25-11-corpus-backfill
M25-12-e2e-observability
```

No agrupar varias fases en un único commit.

## 7. Prohibiciones explícitas para evitar soluciones rápidas incorrectas

- No convertir `BudgetScope` en `Project` cambiando solo el nombre.
- No guardar marca/hotel únicamente dentro de JSON sin índices ni claves foráneas.
- No fusionar proyectos por similitud semántica.
- No usar cliente/proveedor como clave de proyecto.
- No borrar duplicados físicos sin conservar todas sus apariciones.
- No crear presupuesto desde la penúltima carpeta genérica.
- No omitir OCR para toda la carpeta `IMAGENES`.
- No tratar toda salida VLM como tabla.
- No aceptar confianza fija para medidas o texto visual.
- No usar un único `session_id` para todos los chats.
- No filtrar permisos después de haber construido el prompt.
- No subir el corpus completo por un único multipart HTTP.
- No ejecutar un backfill sin `dry-run`, checkpoint e idempotencia.
- No modificar `D:\TEST2025\2025` para adaptar la aplicación.

## 8. Definición de terminado

El trabajo completo solo está terminado cuando:

1. Backend y frontend compilan.
2. Migraciones funcionan desde una base limpia y desde backup.
3. Los 31.323 archivos son visibles como apariciones sin modificar el origen.
4. Cada aparición tiene presupuesto, marca, categoría y hotel cuando corresponda.
5. Duplicados físicos conservan todas sus relaciones.
6. Las imágenes se procesan según su naturaleza y son consultables.
7. El dossier de proyecto reúne toda la información relevante.
8. Las conversaciones tienen contexto independiente.
9. No existen fugas entre ámbitos de permisos.
10. Las respuestas económicas, documentales y visuales citan su fuente.
11. Los datos dudosos se presentan como dudosos y pueden revisarse.
12. El corpus fijo conserva exactamente su estructura y contenido.

## 9. Instrucción corta para entregar a Mimo 2.5

```text
Lee completo PLAN_MIMO_2_5_CORRECCIONES_INTEGRALES.md y AGENTS.md.
Ejecuta solamente la siguiente fase pendiente. No avances a otra fase.
Preserva el worktree existente y no modifiques D:\TEST2025\2025.
Antes de editar, inspecciona todos los archivos indicados en la fase.
Añade pruebas para cada cambio y no declares la fase terminada si backend o frontend no compilan.
Al finalizar entrega archivos cambiados, migraciones, pruebas, riesgos pendientes y confirmación de que el corpus original no fue modificado.
```
