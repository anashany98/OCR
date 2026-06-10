> 📌 Este documento es un **brief de trabajo para una IA de código** (Cursor / Claude Code / similar). Copia su contenido a `docu-intel/AGENTS.md` (o pásalo como prompt). El objetivo: **mejorar la precisión del OCR y la calidad de las respuestas de IA**. Es una **herramienta interna** → NO trabajes en hardening multi-tenant, rate-limiting ni rotación de secretos en esta tanda.

## 0. Contexto y reglas
- **Repo:** backend FastAPI + Celery. Python 3.11. OCR en `app/ocr/`, IA en `app/ai/`, recuperación en `app/services/`.
- **Stack OCR:** Tesseract 5 (CPU) → PaddleOCR 3.x (GPU) → PP-Structure (GPU, tablas/layout), orquestado por `CascadingOCREngine`.
- **Stack IA:** chunking → embeddings (OpenAI-compat o sentence-transformers local) → pgvector + búsqueda híbrida + reranker cross-encoder → respuesta *grounded* con LLM local.
- **GPUs:** 2× RTX 4070, una por worker vía `CUDA_VISIBLE_DEVICES`.

**Reglas para el agente:**
1. **No rompas la interfaz `BaseOCREngine`** (`extract(image_path: Path) -> OCRResult`) ni la firma pública de `embed_many` / `search_*`.
2. **Añade tests** para cada cambio de comportamiento y mantén verdes los existentes.
3. Cada motor OCR sigue siendo **stateless por página**; no introduzcas estado global salvo singletons de modelo ya existentes.
4. Cambios **incrementales y revisables**: un commit por tarea (`O1`, `A1`…).
5. No introduzcas dependencias nuevas sin añadirlas a `requirements.txt` y al `Dockerfile`.
6. Respeta la política existente "sin hash fallback silencioso" en embeddings.

---

# BLOQUE OCR

## O1 · Conectar el preprocesado (hoy está muerto) 🔴
**Archivo:** `app/ocr/preprocess.py`, `app/ocr/tesseract.py`, `app/ocr/paddle.py`, `app/ocr/pp_structure.py`
**Problema (verificado):** `preprocess_for_ocr()` existe pero **ningún motor lo llama**. El preprocesado es el factor que más sube la precisión en escaneos, y ahora mismo no se aplica nunca.
**Matiz crítico:** la binarización adaptativa actual (`adaptiveThreshold`) **ayuda a Tesseract pero perjudica a PaddleOCR y PP-Structure**, que esperan imagen en color/gris. El preprocesado debe ser **específico por motor**.
**Cambio requerido:**
- Añadir dos funciones en `preprocess.py`:
	- `preprocess_for_tesseract(path)` → gris + denoise + deskew + binarización adaptativa + upscaling si DPI bajo.
	- `preprocess_for_paddle(path)` → solo deskew + upscaling + (opcional) denoise suave, **sin binarizar**.
- Llamar al preprocesado adecuado al inicio de cada `extract()`. Trabajar sobre una copia temporal; no machacar el original.
- Manejar errores devolviendo la ruta original (como ya hace), pero **logueando** el fallo.
**Aceptación:** un escaneo inclinado 3° y con ruido produce más texto y mayor confianza media que sin preprocesar (test con imagen fixture).

## O2 · Añadir deskew + corrección de orientación + DPI 🔴
**Archivo:** `app/ocr/preprocess.py`
**Problema:** no hay deskew, ni corrección de orientación (90°/180°), ni normalización de resolución. Son las causas más frecuentes de mal OCR.
**Cambio requerido:**
```python
# Pseudocódigo de referencia
def _deskew(gray):
    coords = cv2.findNonZero(cv2.bitwise_not(gray))
    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    if abs(angle) < 0.5:  # no rotar por ruido
        return gray
    (h, w) = gray.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(gray, M, (w, h),
                          flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)
```
- Orientación: usar Tesseract OSD (`pytesseract.image_to_osd`) para detectar rotación de 90/180/270 y corregirla antes del OCR.
- DPI: si la imagen es pequeña (lado menor < ~1500 px), **upscalar ×2** con `cv2.INTER_CUBIC` antes de OCR. Renderizar PDFs a **300 DPI** en el paso de rasterizado (revisar el parser PDF).
**Aceptación:** test con imagen rotada 90° → texto recuperado correctamente.

## O3 · Dejar de elegir el resultado "ganador" por longitud 🔴
**Archivo:** `app/ocr/cascading.py` (`_is_better`, `_is_acceptable`, `_try_tier3`)
**Problema (verificado):** `_is_better` decide por **número de caracteres** ("strictly more text"); `_try_tier3` solo acepta PP-Structure si produce *más caracteres*. Un motor que mete ruido (más caracteres) gana al bueno.
**Cambio requerido:** introducir un score de calidad y comparar por él:
```python
def _quality(result) -> float:
    text = (result.text or "").strip()
    if not text:
        return 0.0
    alnum = sum(c.isalnum() or c.isspace() for c in text)
    density = alnum / max(len(text), 1)        # penaliza basura simbólica
    conf = result.confidence if result.confidence is not None else 0.5
    length_factor = min(len(text) / 500.0, 1.0)  # satura, no premia infinito
    return conf * 0.5 + density * 0.3 + length_factor * 0.2
```
- `_is_better(cand, base)` → `_quality(cand) > _quality(base) + epsilon`.
- Tier 3 (PP-Structure) gana solo si su `_quality` supera al mejor previo, no por longitud.
**Aceptación:** texto con muchos símbolos pero largo NO sustituye a un texto limpio y corto de alta confianza (test unitario de `_quality`).

## O4 · No silenciar el fallback de la cascada 🟠
**Archivo:** `app/ocr/cascading.py`
**Problema (verificado):** el `except Exception:` que captura el fallo de Tier 2 y Tier 3 **no loguea nada** y devuelve el primario. Degradación invisible.
**Cambio requerido:**
- Añadir `logger = logging.getLogger("app.ocr.cascading")` y loguear a WARNING el motor que falló y la excepción.
- Añadir métrica `track_ocr_cascade_fallback(engine_name, reason)` (crear en `app/services/metrics.py`).
- Registrar para cada página qué tier ganó (ya hay `self._name`; exponérlo como métrica `ocr_tier_used_total{tier}`).
**Aceptación:** al forzar excepción en el fallback, aparece un WARNING y se incrementa la métrica.

## O5 · Pasar el idioma configurado a PaddleOCR (hoy hardcoded) 🟠
**Archivo:** `app/ocr/paddle.py`, `app/ocr/factory.py`
**Problema (verificado):** `PaddleOCR(use_angle_cls=True, lang="es", ...)` tiene el idioma **hardcoded** e ignora settings. Además `_get_gpu_device()` está definido pero **nunca se usa**.
**Cambio requerido:**
- `PaddleOCREngine.__init__(self, lang: str | None = None)` y leer `settings.paddle_lang` (añadir setting, default `"es"`). Pasar `lang` al constructor de `PaddleOCR`.
- Usar `_get_gpu_device()` para fijar el dispositivo explícitamente, o eliminar la función muerta.
- Revisar API de PaddleOCR 3.x: `use_angle_cls` está deprecado en favor de `use_textline_orientation`. Ajustar para evitar warnings/fallos futuros.
**Aceptación:** cambiar el setting de idioma se refleja en el motor; sin parámetros deprecados.

## O6 · Init de modelos cancelable y reutilizado (fuga de hilos) 🟠
**Archivo:** `app/ocr/paddle.py`, `app/ocr/pp_structure.py`, `app/ocr/factory.py`
**Problema (verificado):** ambos motores inicializan el modelo en un **hilo daemon con `join(timeout)`**. Si vence el timeout, el hilo **sigue vivo** cargando el modelo → fuga de memoria/VRAM. Además `_CascadingFactory.__new__` reconstruye los motores en cada instanciación y depende de la "convención de singleton del worker".
**Cambio requerido:**
- Precargar los motores **una vez** en el arranque del worker Celery (`worker_process_init`) y guardarlos en singleton de módulo. Eliminar la reconstrucción por instancia.
- Para el timeout de carga: si vence, marcar el motor como no disponible y propagar error claro, sin dejar hilos huérfanos (usar un flag de cancelación o cargar en el hilo principal del worker al iniciar).
**Aceptación:** procesar 100 documentos no incrementa el número de hilos vivos ni recarga el modelo.

## O7 · (Opcional, alto valor interno) Tier 4 VLM-OCR para casos difíciles 🟡
**Archivo:** `app/ocr/dots_mocr.py` (hoy stub con `NotImplementedError`)
**Problema:** los casos más duros (fotos de móvil, sellos, manuscrito, tablas complejas) superan a Tesseract/Paddle. Al ser herramienta interna, **se puede asumir más latencia a cambio de precisión**.
**Cambio requerido:** implementar `DotsMOCREngine.extract()` como cliente HTTP a un endpoint VLM-OCR (dots.ocr / Qwen2-VL / GOT-OCR servido en LM Studio/vLLM). Conectarlo como **último escalón** de la cascada, gateado por setting y por `_quality` bajo de Tier 1-3. Mantener el fallback al mejor resultado previo si falla.
**Aceptación:** con el setting activado, una página que Tesseract+Paddle resuelven mal mejora su `_quality` vía Tier 4.

---

# BLOQUE IA / RECUPERACIÓN

## A1 · BUG: la query se embebe en modo *passage* 🔴
**Archivo:** `app/services/embeddings.py`, `app/services/search_service.py`
**Problema (verificado):** `search_semantic()` llama a `embed_text(query)` → `embed_many([query])`. Para `local_sentence_transformers`, `embed_many` usa **modo passage** (`passage:` prefix). Los modelos **asimétricos** (IBM Granite, configurado por defecto) exigen prefijo `query:` en las consultas. Embeber la query como passage **degrada notablemente el recall**.
**Cambio requerido:**
- Añadir `embed_query_text(text)` que, para proveedor `local_sentence_transformers`, use `get_local_embedding_client().embed_query(text)` (modo query). Para OpenAI-compat (sin prefijos) se comporta igual que ahora.
- En `search_service.search_semantic`, sustituir `embed_text(normalized)` por `embed_query_text(normalized)`.
- Verificar que el **indexado** (chunks) sigue en modo passage (correcto hoy).
**Aceptación:** test que confirme que el embedding de la query usa el prefijo `query:` con modelos asimétricos; mejora medible de recall en un set de preguntas de prueba.

## A2 · Fusión híbrida sin normalizar escalas 🔴
**Archivo:** `app/services/search_service.py` (`merge_hybrid_results`)
**Problema (verificado):** la búsqueda de texto asigna scores fijos (`1.0` página, `1.2` bloque, ×1.1) mientras la semántica usa coseno en `[0,1]` (×0.75/×0.9). Las escalas no son comparables → **el texto casi siempre domina** y el ranking final ignora la semántica.
**Cambio requerido:** usar **Reciprocal Rank Fusion (RRF)**, robusto y sin calibrar escalas:
```python
def merge_hybrid_results(text_results, semantic_results, limit=10, k=60):
    scores, items = {}, {}
    for rank, r in enumerate(text_results):
        key = (r.document_id, r.page_number, r.block_id)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        items[key] = r
    for rank, r in enumerate(semantic_results):
        key = (r.document_id, r.page_number, r.block_id)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        items.setdefault(key, r)
    ranked = sorted(scores, key=scores.get, reverse=True)[:limit]
    return [replace(items[k2], score=scores[k2], source_type="hybrid_rrf") for k2 in ranked]
```
**Aceptación:** un documento que solo aparece en semántica con alta relevancia puede superar a un match léxico débil.

## A3 · Chunking semántico + metadatos 🟠
**Archivo:** `app/services/chunking.py`
**Problema (verificado):** `build_chunks` parte por ventana de **220 palabras / 40 de solape**, ignorando frases, párrafos, páginas y tablas. Rompe el contexto justo donde están los datos.
**Cambio requerido:**
- Trocear respetando **límites de frase/párrafo** (no cortar a mitad de frase). Mantener `max_words`/`overlap` como tope, no como criterio único.
- **No mezclar páginas** distintas en un mismo chunk.
- Mantener **filas de tabla** juntas (usar `block_type == "table"` de PP-Structure cuando exista).
- Prepend de cabecera con metadatos al texto embebido del chunk, p. ej.: `[tipo=factura | fichero=2024_0345.pdf | pág=2] <texto del chunk>`
**Aceptación:** los chunks no parten frases; preguntas sobre un campo concreto recuperan el chunk correcto con su metadato.

## A4 · Extracción estructurada determinista de campos 🟠
**Archivo:** `app/services/business_extraction.py`, `app/services/plan_extraction.py`, modelos
**Problema:** para facturas/presupuestos/albaranes, confiar en que el LLM lea bien importes/fechas es frágil. Esos documentos tienen **campos clave deterministas**.
**Cambio requerido:**
- Reforzar la extracción por reglas/regex sobre el texto OCR: `nº factura`, `base imponible`, `IVA`, `total`, `fecha`, `proveedor`, `NIF/CIF`, `nº presupuesto`.
- Persistir esos campos como propiedades del documento (columnas/tabla dedicada) e **indexarlos**.
- Inyectarlos como contexto fiable en el prompt de la IA, y permitir responder agregaciones ("suma de facturas de mayo") por **SQL exacto**, no por el LLM.
**Aceptación:** dado un PDF de factura de prueba, los campos clave quedan extraídos y consultables por SQL.

## A5 · Modo query/passage y validación de dimensión en embeddings 🟠
**Archivo:** `app/services/embeddings.py`, `app/services/vector_store.py`
**Problema (verificado):** `coerce_embedding_dimensions` **rellena con ceros o trunca en silencio** si la dimensión no coincide → enmascara un cambio de modelo y produce búsquedas sin sentido. `_vector_literal` no valida dimensión contra la columna pgvector.
**Cambio requerido:**
- Si la dimensión devuelta ≠ `settings.embedding_dimensions`, **lanzar error explícito** (no padear) salvo flag de migración.
- Validar dimensión del embedding de query contra la de la columna antes de la consulta SQL, con mensaje claro.
- Confirmar que el modelo de embeddings es **multilingüe** (Granite multilingüe / bge-m3 / multilingual-e5); documentarlo en settings.
**Aceptación:** un mismatch de dimensión falla rápido con mensaje claro, no con error críptico de Postgres.

## A6 · Robustez del cliente LLM y detección de idioma 🟡
**Archivo:** `app/ai/local_client.py`, `app/ai/agent.py`
**Problema (verificado):** no hay reintentos/backoff ni circuit breaker en las llamadas al LLM/embeddings; la detección de idioma (`_response_looks_spanish`) es heurística y descarta respuestas buenas por falsos positivos; `memory_block` usa heurística de "parece follow-up".
**Cambio requerido:**
- Añadir reintentos con backoff exponencial + jitter y un timeout claro en `local_client`; circuit breaker simple (abrir tras N fallos consecutivos).
- Sustituir `_response_looks_spanish` por una librería (`langdetect`/`fasttext`).
- Hacer la detección de follow-up más robusta o usar siempre las últimas N respuestas con desambiguación explícita.
**Aceptación:** un proveedor lento/intermitente se reintenta con backoff; respuestas válidas en español ya no se descartan.

## A7 · Marcar contexto de baja confianza OCR en el prompt 🟡
**Archivo:** `app/ai/agent.py`
**Problema:** el contexto ya incluye `Confianza=...`, pero el prompt no instruye al modelo a **matizar** cuando la fuente viene de OCR dudoso (`< 0.70`).
**Cambio requerido:** marcar explícitamente esos chunks (p. ej. `[OCR DUDOSO]`) y añadir al system prompt: "si la fuente está marcada como OCR dudoso, adviértelo en la respuesta". Añadir job que re-OCR + re-embeba documentos `needs_reembedding`/baja confianza cuando mejore el OCR.
**Aceptación:** una respuesta basada en página de baja confianza incluye una advertencia.

---

# BLOQUE PLANOS

## PL1 · Usar la escala (hoy se extrae y se descarta) 🔴
**Archivo:** `app/services/plan_extraction.py`, modelos `Plan/PlanDimension/PlanRoom`
**Problema (verificado):** `_extract_scale` obtiene `scale_ratio` (p. ej. 1:100) y se persiste, pero **nunca se usa para calcular nada**. Las medidas reales solo aparecen si vienen impresas como texto ("Salón 20 m2"). El propósito de un plano —convertir distancias del dibujo a metros con la escala— no existe.
**Cambio requerido:** medir longitudes de líneas de cota en píxeles (desde la capa de layout/OCR con bbox) y convertir a metros usando `scale_ratio` y el DPI de rasterizado. Validar coherencia con las cotas impresas detectadas.
**Aceptación:** dada una cota gráfica conocida y escala 1:100, el valor en metros calculado coincide (±tolerancia) con la cota impresa.

## PL2 · Poblar geometría: bbox y página (hoy siempre None) 🔴
**Archivo:** `app/services/plan_extraction.py`
**Problema (verificado):** `_extract_dimensions(text)` solo recibe texto plano; `bbox_x1..y2` y `page_number` de `PlanDimension` se rellenan **siempre con None**. Sin posición no se puede localizar ni verificar ninguna cota sobre el dibujo (ni aplicar PL1).
**Cambio requerido:** pasar a la extracción la estructura OCR con posiciones (PP-Structure / cajas por token) y rellenar bbox + página de cada cota y estancia.
**Aceptación:** las cotas extraídas tienen coordenadas y número de página no nulos en un PDF de prueba.

## PL3 · Parsear pares "A × B" y poblar ancho/alto (campos muertos) 🟠
**Archivo:** `app/services/plan_extraction.py`
**Problema (verificado):** `width_m`, `length_m` y `polygon_json` de `PlanRoom` son **siempre None**. No se parsea el patrón habitual de acotado de estancias "3,50 × 4,20 m".
**Cambio requerido:** añadir regex para `A x B (m)` (admitir `x`/`×`/`X`), poblar `width_m`/`length_m` y derivar `area_m2` cuando no venga impresa como texto.
**Aceptación:** "3,50 x 4,20 m" produce width=3.5, length=4.2 y área≈14.7.

## PL4 · Arreglar `_parse_number` (decimal/miles ambiguo) 🟠
**Archivo:** `app/services/plan_extraction.py`
**Problema (verificado):** `value.replace(".", "").replace(",", ".") if "," in value else value`. Con coma elimina **todos los puntos** como separador de miles; sin coma deja el punto tal cual. "1.234 m" → 1.234 en vez de 1234, y mezcla convenciones decimales sin saber cuál aplica → medidas erróneas en silencio.
**Cambio requerido:** detectar el formato por regex (`\d{1,3}(\.\d{3})+(,\d+)?` = es-ES con miles; `\d+(\.\d+)?` = decimal en) y parsear en consecuencia. Cubrir con tests.
**Aceptación:** "1.234,56"→1234.56, "1,234.56"→1234.56, "3,5"→3.5, "12.5"→12.5.

## PL5 · `_looks_like_plan`: coincidencia por palabra, no subcadena 🟠
**Archivo:** `app/services/plan_extraction.py`
**Problema (verificado):** `keyword in normalized` hace que "planta" matchee "implantación", "cota" matchee "mascota" y "m2" casi cualquier cosa. Como `persist_plan_extraction` también se dispara con `_looks_like_plan`, puede crear filas `Plan` para documentos que no son planos.
**Cambio requerido:** usar límites de palabra (`\b`) y exigir **≥2 señales distintas** antes de clasificar como plano. Eliminar el `"seccion"` duplicado de `PLAN_KEYWORDS`.
**Aceptación:** un documento con "implantación" pero sin contexto de plano NO se clasifica como plano.

## PL6 · Endurecer `ROOM_AREA_RE` y filtros de estancia 🟡
**Archivo:** `app/services/plan_extraction.py`
**Problema (verificado):** "planta" no está en `_is_non_room_label` → "Planta baja 20 m2" entra como estancia; los nombres con número ("Dormitorio 1") se parsean mal porque la clase `[A-Za-z ]` corta en el dígito; el match perezoso con espacios iniciales puede arrastrar texto contiguo. Además `_clean_room_name` aplica `.title()` y rompe nombres compuestos ("cocina-office" → "Cocina-Office").
**Cambio requerido:** añadir "planta" (y similares) a no-estancias, permitir dígitos en nombres, anclar mejor el inicio del nombre y respetar la capitalización original.
**Aceptación:** "Planta baja 20 m2" no genera estancia; "Dormitorio 1 15 m2" → estancia "Dormitorio 1" con área 15.

---

# BLOQUE FRONTEND (workstream aparte: UX + mantenibilidad)
> Nota: este bloque NO afecta a OCR/IA; abórdalo como tanda independiente. Stack: React + Vite + React Router + TanStack Query.

## F1 · Code-splitting de las páginas con React.lazy 🔴
**Archivo:** `frontend/src/routes/router.tsx`
**Problema (verificado):** el router importa las 16 páginas de forma *eager*. Hay páginas muy grandes (`ChatPage` ~49 KB, `PlanoAnnotationPage` ~36 KB, `DocumentDetailPage` ~33 KB, `AdminPage` ~31 KB, `WorkInboxPage` ~31 KB) que entran en el bundle inicial.
**Cambio requerido:** convertir cada import de página en `React.lazy(() => import(...))` y envolver las rutas/`<Outlet>` en `<Suspense fallback={<LoadingState/>}>`.
**Aceptación:** el bundle inicial no contiene Chat/Admin/PlanoAnnotation; se cargan bajo demanda (verificable con `vite build` + análisis de chunks).

## F2 · Proteger rutas por rol en el router (no solo en el menú) 🔴
**Archivo:** `frontend/src/routes/router.tsx`, `frontend/src/components/layout/PermissionGate.tsx`
**Problema (verificado):** `canSee()` en `Sidebar` solo **oculta** enlaces; las rutas `/jobs`, `/admin`, `/plans` no están protegidas → un usuario sin rol entra tecleando la URL.
**Cambio requerido:** envolver las rutas sensibles con `PermissionGate`/`RequireRole` según sus `roles` (`admin`/`gestor`).
**Aceptación:** un usuario `operario` que navega a `/admin` por URL ve un "no autorizado", no la página.

## F3 · `errorElement` + ruta 404 🟠
**Archivo:** `frontend/src/routes/router.tsx`
**Problema (verificado):** `createBrowserRouter` no define `errorElement` (pese a existir `ErrorBoundary.tsx`) ni una ruta catch-all `*`.
**Cambio requerido:** añadir `errorElement` en la ruta raíz y una ruta `path: "*"` → `NotFound`.
**Aceptación:** una URL inexistente y un error de render muestran un fallback, no una pantalla en blanco.

## F4 · Partir `AdminPage` en rutas anidadas 🟠
**Archivo:** `frontend/src/pages/AdminPage.tsx`, `routes/router.tsx`, `Sidebar.tsx`
**Problema (verificado):** `AdminPage` (31 KB) gestiona 6 pestañas con `useState(activeTab)` + `setSearchParams({tab})`; declara **decenas de `useState`** y **todas las `useQuery` se ejecutan al montar** sin importar la pestaña activa. Los enlaces del sidebar usan `/admin?tab=…#hash`, pero el `#hash` (duplicates/quarantine) no se gestiona.
**Cambio requerido:** rutas anidadas `/admin/{operativa,sistema,integraciones,acceso,calidad,aprendizaje}` con componentes *lazy*; cada uno hace su propio *fetch*. El `Sidebar` enlaza a esas rutas (sin `?tab`/`#hash`).
**Aceptación:** entrar en `/admin/acceso` solo dispara las queries de acceso; el deep-link directo funciona y marca el activo correcto.

## F5 · Recuperar barra lateral persistente en escritorio 🟠
**Archivo:** `frontend/src/components/layout/AppShell.tsx`, `Sidebar.tsx`
**Problema (verificado):** `AppShell` está marcado como "no persistent sidebar": la navegación es **solo drawer** (hamburguesa / ⌘B). En una herramienta interna de uso intensivo obliga a abrir el drawer para cada salto, y el `SidebarNav` inline quedó como código *legacy*.
**Cambio requerido:** renderizar `SidebarNav` de forma persistente en `lg+` y el `SidebarDrawer` solo en móvil; eliminar la duplicación *legacy*.
**Aceptación:** en escritorio la navegación está siempre visible; en móvil se mantiene el drawer.

## F6 · Endpoint de conteo para el badge de Tareas 🟠
**Archivo:** `AppShell.tsx`, `Sidebar.tsx`, backend `app/api/routes`
**Problema (verificado):** tanto `AppShell` como `Sidebar` llaman a `api.workInbox({ limit: 200 })` **cada 30 s** solo para `data.length` (el propio comentario del código pide un endpoint de conteo y quitar el cap). Además la query está duplicada en dos componentes.
**Cambio requerido:** añadir `GET /work-inbox/count` y consumirlo desde una sola query compartida; quitar el cap 200.
**Aceptación:** el badge no descarga 200 filas; el conteo viene de una query dedicada y única.

## F7 · Una sola fuente de verdad para etiquetas/títulos 🟡
**Archivo:** `Sidebar.tsx` (`NAV_GROUPS`), `AppShell.tsx` (`getPageTitle`), `AdminPage.tsx` (`tabLabels`)
**Problema (verificado):** los títulos/labels están triplicados → riesgo de *drift*; `getPageTitle` no cubre `/documents/:id/annotate-plan` (cae a "Docu-Intel").
**Cambio requerido:** derivar el título desde la config de navegación o desde el `handle` de ruta (`useMatches`).
**Aceptación:** renombrar o añadir una pestaña actualiza a la vez el menú y el título.

## F8 · Descomponer páginas monolíticas 🟡
**Archivo:** `ChatPage.tsx`, `PlanoAnnotationPage.tsx`, `DocumentDetailPage.tsx`, `WorkInboxPage.tsx`
**Problema (verificado):** páginas de 20–49 KB sin trocear, difíciles de mantener y testear.
**Cambio requerido:** extraer subcomponentes y *hooks* de datos (`useXxx`) por sección.
**Aceptación:** ninguna página supera el umbral de líneas acordado; la lógica de datos vive en hooks testeables.

## F9 · Accesibilidad y pulido 🟡
**Archivo:** `Sidebar.tsx`, `AppShell.tsx`, `AdminPage.tsx`
**Problema (verificado):** el badge numérico no tiene `aria-label`; el estado de carga de sesión es texto plano ("Cargando sesión…") existiendo `LoadingState`; el reproceso en lote usa `window.confirm`.
**Cambio requerido:** `aria-label` en badges ("N tareas pendientes"), `aria-current` en el activo, usar `LoadingState`, y sustituir `window.confirm` por un diálogo de confirmación accesible.
**Aceptación:** auditoría a11y básica sin errores en navegación y badges.

---

## Orden de ejecución sugerido

| # | Tarea | Impacto |
|---|-------|---------|
| 1 | A1 — Fix query/passage en embeddings | 🔴 Recuperación |
| 2 | O1 + O2 — Preprocesado real (deskew/DPI, por motor) | 🔴 Precisión OCR |
| 3 | A2 — Fusión híbrida con RRF | 🔴 Ranking |
| 4 | O3 + O4 — Score de calidad + logging de cascada | 🟠 Calidad + observabilidad |
| 5 | A3 + A4 — Chunking semántico + extracción de campos | 🟠 Utilidad real |
| 6 | O5 + O6 — Idioma configurable + init sin fugas | 🟠 Estabilidad |
| 7 | A5 + A6 + A7 — Validación dimensión, robustez LLM, OCR dudoso | 🟡 Robustez |
| 8 | O7 — Tier 4 VLM-OCR (opcional) | 🟡 Casos difíciles |
| 9 | PL1–PL6 — Planos: usar escala, geometría y parsing robusto | 🟠 Función planos |
| 10 | F1 + F2 — Frontend: code-splitting + gating de rutas por rol | 🔴 Front (workstream aparte) |

## Checklist de aceptación global
- [ ] Tests existentes en verde + tests nuevos por tarea.
- [ ] La query usa modo `query:` con modelos asimétricos (A1).
- [ ] El preprocesado se aplica y es específico por motor (O1/O2).
- [ ] El "ganador" de la cascada se decide por calidad, no por longitud (O3).
- [ ] Las degradaciones de OCR se loguean y se miden (O4).
- [ ] La fusión híbrida no la domina siempre el texto (A2).
- [ ] No hay fugas de hilos ni recargas de modelo por documento (O6).
- [ ] Mismatch de dimensión de embedding falla con mensaje claro (A5).
- [ ] Planos: la escala se usa para calcular medidas y las cotas tienen bbox/página (PL1/PL2).
- [ ] Planos: `_parse_number`, parsing "A×B" y clasificación de plano cubiertos con tests (PL3/PL4/PL5).
- [ ] Frontend: páginas pesadas cargadas con `React.lazy` y rutas sensibles protegidas por rol en el router (F1/F2).
- [ ] Frontend: `AdminPage` dividido en rutas anidadas y badge de Tareas servido por endpoint de conteo (F4/F6).
