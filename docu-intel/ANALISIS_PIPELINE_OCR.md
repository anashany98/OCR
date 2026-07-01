# Análisis del pipeline OCR / Cascada — Optimización

> 📌 **Análisis técnico del flujo OCR completo**, basado en lectura del código en
> producción (rama `feature/nuextract3-integration`). Cubre: rasterizado de PDF,
> preprocesado, cascada multi-tier, agregación de confianza, carga de modelos en
> workers, cachés y archivos temporales.
>
> **Conclusión principal:** el AGENTS.md raíz está **desactualizado**. Las tareas
> O1, O2, O3, O4, O5, O6 **ya están implementadas**. El pipeline es
> estructuralmente sólido; los problemas reales son de **calibración del
> preprocesado, paralelismo ausente y trabajo duplicado**, no de arquitectura.
>
> Para una IA de código: cada sección tiene un bloque `FIX` accionable con
> archivos, líneas y criterios de aceptación. Un commit por fix.

---

## 0. Mapa del flujo real

```
Documento (PDF/imagen)
  │
  ├─[PDF] parsers/pdf.py: parse_pdf()
  │    ├─ fitz (PyMuPDF) abre el PDF
  │    ├─ classify_content() (content_router)
  │    └─ FOR cada página (SECUENCIAL, pdf.py:600):  ← 🔴 cuello de botella
  │         ├─ page.get_text("text") → ¿≥30 chars?
  │         │    ✓ Digital fast path: confianza=1.0, render 144 DPI preview
  │         │    ✗ Scanned → _ocr_with_dpi_ladder()
  │         │                ├─ DPI ladder [300,400,600] (600 solo si 300+400 vacíos)
  │         │                ├─ _render_page_to_image() (JPEG→PNG fallback)
  │         │                └─ ocr_engine.extract(image)  ← CascadingOCREngine
  │         │                      ├─ Tier1 Tesseract (CPU)
  │         │                      ├─ Tier2 PaddleOCR (GPU)
  │         │                      ├─ Tier3 PP-Structure (GPU, layout)
  │         │                      └─ Tier4 DotsMOCR/NuExtract3 (VLM)
  │         └─ ExtractedPage(...)
  │
  └─[Imagen] parsers/image.py → ocr_engine.extract() directo
```

Persistencia (`document_processing_core.py:469`): una fila `DocumentPage` por
página + `DocumentBlock` por bloque OCR. La confianza del **documento** no se
persiste; se recalcula en `_quality_score` (`quality.py:196`) desde las páginas.

---

## 1. Preprocesado — problemas de calibración (la causa del 60% de los `needs_review`)

**Archivo:** `app/ocr/preprocess.py`

### Estado real (contrario al AGENTS.md)
- `preprocess_for_tesseract()` ✅ existe y se llama (`tesseract.py:59`).
- `preprocess_for_paddle()` ✅ existe y se llama (`paddle.py:171`).
- `preprocess_adaptive()` ✅ decide scan vs foto (`preprocess.py:108`).
- Deskew, OSD (orientación 90/180/270), upscaling, denoise, CLAHE, sharpen ✅.

### Problemas

#### 🔴 1.1 — `_looks_like_scan` clasifica mal → Tesseract pierde binarización
`preprocess.py:101` clasifica como scan solo si `extreme_ratio > 0.55 AND
color_var < 70`. Una factura escaneada con logo/sello de color baja
`extreme_ratio` → se trata como **foto** → path `preprocess_for_manuscript`
(**sin binarizar**) → Tesseract pierde su mayor ventaja. Sin métricas del path
elegido, el error es invisible.

Resultado en BD: ~229 `page_without_text` y parte de los 343 `low_ocr_confidence`
vienen de fotos/scans mal clasificados donde Tesseract no binariza.

**FIX 1.1:**
- Añadir métrica `track_preprocess_path_chosen(path_type)` (scan / manuscript /
  fallback) en `preprocess_adaptive`. Exponer en `/metrics`.
- Calibrar los umbrales de `_looks_like_scan` con una muestra de imágenes reales
  de los docs en `needs_review`. Alternativa más robusta: **probar ambos paths
  para Tesseract** y elegir por `_quality` (ver FIX 1.4).
- **Aceptación:** la métrica permite ver la distribución scan vs foto; tras
  calibrar, el % de `page_without_text` baja.

#### 🟠 1.2 — PP-Structure se salta el caché de preprocesado
`pp_structure.py:74` llama a `preprocess_for_paddle()` **directamente**, no a
`preprocess_adaptive()`. Consecuencia: aunque Tier 2 (Paddle) ya preprocesó la
imagen y la cacheó bajo `(path, "paddleocr")`, Tier 3 **recomputa** el
preprocesado completo (denoise, deskew, CLAHE, upscaling). Hasta 3 PNGs
temporales creados y borrados por página en una cascada completa.

**FIX 1.2:**
- Cambiar `pp_structure.py:74` para llamar `preprocess_adaptive(image_path,
  engine=self.name)`.
- **Aceptación:** en una cascada Tier2→Tier3, el preprocesado se ejecuta una
  sola vez (caché hit); un test lo verifica mockeando `_looks_like_scan`.

#### 🔴 1.3 — El caché `_preprocess_cache` es inefectivo entre motores
Cada motor borra su temp en `finally` (`unlink`). El caché guarda el `Path`, y
`preprocess_adaptive` comprueba `.exists()` (`preprocess.py:124`) → siempre
falla tras el motor anterior → **recomputa**. El caché solo pega si el mismo
motor se llama dos veces (no ocurre en cascada normal). Resultado: denoise +
deskew + OSD se repiten por cada tier.

**FIX 1.3 (la optimización de mayor impacto en CPU/latencia):**
- Centralizar la vida de los temps: que `CascadingOCREngine.extract()` cree un
  único temp por `(path, engine)` y lo borre al **final de la página**, no por
  motor. O devolver arrays numpy en memoria en vez de escribir PNG a disco.
- Como mínimo, cachear por separado: (a) la decisión `_looks_like_scan`
  (barata, independiente del motor) y (b) el resultado OSD `_detect_osd_rotation`
  (caro, ~200ms, independiente del motor).
- **Aceptación:** un test de instrumentación cuenta las llamadas a
  `_detect_osd_rotation` y `_looks_like_scan` en una cascada Tier1→2→3: deben
  ser **1 cada una**, no 2-3.

#### 🟡 1.4 — No hay retroalimentación de `_quality` al preprocesado
Si `_looks_like_scan` eligió mal, Tesseract no recupera: la cascada escala a
Paddle pero **no prueba la imagen sin binarizar para Tesseract**. El
preprocesado es "una sola oportunidad".

**FIX 1.4 (opcional, alto valor):**
- En Tesseract: si `_quality(result) < threshold`, reintentar con el path
  opuesto (binarizado ↔ no-binarizado) y quedarse con el de mayor `_quality`.
- Gatear con un setting para no pagar el coste en docs fáciles.
- **Aceptación:** una imagen de foto mal clasificada produce más texto en el
  reintento binarizado (o viceversa).

---

## 2. Cascada — mezcla de criterios

**Archivo:** `app/ocr/cascading.py`

### Estado real
- `_quality()` ✅ (confianza×0.5 + densidad×0.3 + longitud×0.2).
- `_should_replace_with_fallback()` ✅ (delta de calidad + alnum_gain).
- `_is_better()` ✅ (usa `_quality` + épsilon).
- Logging/métricas de fallback ✅ (`_track_fallback_failure`).
- 4 tiers con circuitos de fallo ✅.

### Problemas

#### 🟠 2.1 — `_try_tier3` mezcla longitud y calidad
`cascading.py:263` rechaza Tier 3 si `len(text) < self.min_chars` (criterio de
**longitud**), pero después decide con `_is_better` (criterio de **calidad**).
Inconsistencia: un Tier 3 con texto corto pero denso y alta confianza se
descarta por longitud antes de evaluarse por calidad. El resto del pipeline ya
migró a `_quality`; este filtro se quedó del diseño antiguo (exactamente lo que
O3 quería eliminar, pero no se aplicó a Tier 3).

**FIX 2.1:**
- Sustituir el filtro de `min_chars` en `cascading.py:263` por un filtro de
  `_quality`: solo rechazar si `_quality(tier3_result) <= QUALITY_EPSILON`
  (es decir, ruido puro).
- Mantener `_is_better` como única comparación posterior.
- **Aceptación:** test con un PP-Structure que devuelve 20 chars limpios y alta
  confianza → ya **no** se descarta por `min_chars`; gana si supera al previo.

#### 🟡 2.2 — `_finalize` evalúa Tier 4 con `_is_better` pero el gate es `_quality`
`cascading.py:274` invoca Tier 4 solo si `_quality(result) <
tier4_quality_threshold` (default 0.62). Bien. Pero `_try_tier4:301` acepta el
resultado VLM con `_is_better(tier4, best_prior)` — un VLM que transcribe bien
texto manuscrito puede tener `confidence=None` (algunos VLMs no dan score) →
`_quality` trata None como 0.5 → puede perder contra un previo mediocre.

**FIX 2.2:**
- Si `tier4_result.confidence is None`, asignar una confianza conservadora
  (p.ej. 0.75, el típico de un VLM bueno) antes de comparar, o comparar por
  densidad + longitud cuando la confianza sea None.
- **Aceptación:** test con un VLM que devuelve texto bueno pero
  `confidence=None` → gana contra un previo de `_quality` 0.55.

---

## 3. Paralelismo de páginas — el cuello de botella principal

**Archivo:** `app/parsers/pdf.py:600`

### Problema 🔴
El bucle `for index, page in enumerate(pdf)` procesa páginas **estrictamente
secuencial**. Para un PDF de 50 páginas escaneadas, son 50 cascadas OCR en
serie (Tier1→2→3 cada una, ~1-5s por página) → **1-4 minutos de procesamiento
secuencial** con la GPU infrautilizada. Con 2× RTX 4070 solo una hace trabajo
mientras la página anterior termina.

**FIX 3.1 (alto impacto en velocidad):**
- Paralelizar el OCR de páginas con un `ThreadPoolExecutor` (GIL no es
  problema: Tesseract/Paddle/PP-Structure liberan el GIL en las llamadas C).
  Renderizar las imágenes en el hilo principal (fitz no es thread-safe para el
  mismo documento) y lanzar `ocr_engine.extract()` en paralelo.
- **Cuidado:** `CascadingOCREngine.current_language` y `_preprocess_cache` son
  estado compartido. Antes de paralelizar hay que (a) hacer `_preprocess_cache`
  thread-local o keyed+frozen, y (b) pasar `current_language` como argumento en
  vez de atributo de instancia, o eliminar el atributo mutado.
- Limitar el grado de paralelismo por setting (`ocr_page_parallelism`, default 2)
  para no saturar VRAM con 2 modelos Paddle concurrentes.
- **Aceptación:** un PDF de 20 páginas escaneadas procesa en ~50% del tiempo
  con `ocr_page_parallelism=2` frente a `=1`; la GPU muestra uso >50% sostenido.

**FIX 3.2 (alternativa más simple, baja riesgo):**
- Si paralelizar within-doc es arriesgado, al menos asegurar que
  `worker_prefect_multiplier=1` (ya está) y que **varios documentos** se
  procesan en workers distintos (escalamiento horizontal). Verificar que los
  workers heavy tengan `--concurrency=1` (un doc a la vez, pero la GPU dedicada)
  o `--concurrency=2` si la VRAM lo permite.

---

## 4. DPI ladder — posible sobre-procesamiento

**Archivo:** `app/parsers/pdf.py:255-325`

### Estado real
`_DPI_LADDER = [300, 400, 600]`. 600 DPI solo si 300+400 dieron **vacío**.
Criterio de "usable" en `_ocr_is_usable` (text ≥30 chars + confianza ≥0.40).

### Problema 🟡
Para una página que 300 DPI resuelve con texto pero confianza 0.45 (justo por
encima del umbral de "usable"), se para la escalada — correcto. Pero el umbral
0.40 es bajo: una página con confianza 0.42 se acepta y no se reintenta a 400
DPI, aunque 400 DPI podría darle 0.75. La cascada interna tampoco re-intenta a
otro DPI (es responsabilidad del parser).

Además: **todo el preprocesado + cascada se ejecuta completo por cada nivel de
DPI** probado. Una página difícil que escala 300→400→600 paga 3× el
preprocesado + 3× la cascada.

**FIX 4.1:**
- Subir `_DPI_MIN_CONFIDENCE` de 0.40 a ~0.55 (alineado con
  `low_ocr_confidence_threshold=0.60` y `quality_score_threshold=0.55`), para
  que más páginas se beneficien del reintentos a 400 DPI.
- Cachear el preprocesado por `(path, dpi)` o reutilizar el render previo. Como
  los DPI distintos producen imágenes distintas, el caché debe ser por render.
- **Aceptación:** tras subir el umbral, el % de páginas con
  `low_ocr_confidence` baja en una muestra de PDFs difíciles; no hay
  regresión de tiempo en PDFs fáciles (cortocircuita en 300 DPI).

---

## 5. Carga de modelos y workers — singleton y VRAM

**Archivos:** `app/ocr/factory.py`, `app/workers/celery_app.py`

### Estado real
- `_engine_singleton` de módulo ✅ (`factory.py:30`) con lock.
- `preload_ocr_engine()` ✅ se llama en `worker_process_init` (`celery_app.py:115`),
  solo en workers heavy.
- `_warm_ocr_engine` + `_exercise` ✅ (compilación con imagen sintética).
- `worker_max_tasks_per_child=50` ✅ (recicla el proceso para liberar VRAM).
- PaddleOCR init con timeout desechable + `_init_failed` flag ✅.

### Problemas

#### 🟠 5.1 — `_get_or_create_engine` no es resistente a reset de proceso
Tras `max_tasks_per_child=50`, Celery recicla el proceso y llama de nuevo a
`worker_process_init`. El `_engine_singleton` global **se reinicia** correctamente
al ser un nuevo proceso. Bien. Pero si `preload_ocr_engine()` falla en el
arranque (GPU no disponible), el worker arranca sin motor y **cada job** intenta
`get_ocr_engine()` que devuelve el singleton `None` → construye bajo demanda →
sin warmup → primer job lento y sin `_exercise`.

**FIX 5.1:**
- Si `preload_ocr_engine` falla en init, el worker debería **abortar** (o al
  menos marcarse como no-OCR-capaz) en vez de arrancar y servir jobs lentos.
  Alternativamente, reintentar el preload en el primer job con backoff.
- **Aceptación:** worker heavy sin GPU al arrancar no acepta jobs OCR (o lo
  hace tras un warmup explícito), no "parece funcionar" pero tarda 50×.

#### 🟡 5.2 — `_warn_if_gpu_requested_but_unavailable` depende de torch
`factory.py:256` importa `torch` solo para comprobar `cuda.is_available()`.
Paddle no requiere torch (usa su propio runtime). Un worker con Paddle+CUDA pero
**sin torch** instalado → el check se salta silenciosamente → no hay warning
aunque la GPU esté caída.

**FIX 5.2:**
- Comprobar GPU con `paddle.is_compiled_with_cuda()` /
  `paddle.device.is_compiled_with_cuda()` o `nvidia-smi`, no con torch. O
  documentar que torch es dependencia obligatoria en workers GPU.
- **Aceptación:** worker GPU con Paddle pero sin torch detecta correctamente
  el estado de CUDA.

---

## 6. Cachés y archivos temporales — fugas y recomputo

**Archivo:** `app/ocr/preprocess.py`

### Estado real
- `_preprocess_cache` (dict global) se limpia por página
  (`clear_preprocess_cache` en `cascading.py:178`).
- Cada motor borra su temp en `finally` ✅.

### Problemas (relacionados con FIX 1.2/1.3, repetidos aquí por impacto)

#### 🔴 6.1 — Temporales en `dir=path.parent`, no en tmp del sistema
`preprocess.py:153` crea `NamedTemporaryFile(dir=path.parent)`. Los temps viven
en la carpeta del documento. Si un proceso muere entre `cv2.imwrite`
(`preprocess.py:51`) y el `finally` del motor, el PNG queda huérfano en la
carpeta del doc → acumulación sin limpieza.

**FIX 6.1:**
- Usar `tempfile.gettempdir()` (o un dir dedicado `settings.cache_dir`) para los
  temps de preprocesado, no `path.parent`.
- Añadir un job de mantenimiento que borre `*.tesseract.png`, `*.paddle.png`,
  `*.manuscript.png` huérfanos mayores de 1h en el dir de temps.
- **Aceptación:** tras matar un worker a mitad de OCR, no quedan temps en la
  carpeta del documento tras 1h.

#### 🟡 6.2 — `.cache/` de HuggingFace crece sin límite
`docu-intel/backend/.cache/huggingface/` ya tiene 2.2 GB (reranker + embeddings).
No hay `HF_HOME` configurado ni GC. Cambiar de modelo suma tamaño sin liberar
el anterior.

**FIX 6.2:**
- Configurar `HF_HOME`/`TRANSFORMERS_CACHE` a un path dedicado en `settings`.
- Job de mantenimiento opcional que purge modelos no referenciados por la
  config actual (avanzado; HF no lo hace solo).
- **Aceptación:** `.cache/` vive en un path configurable; un doc explica cómo
  limpiarlo.

---

## 7. Agregación de confianza — inconsistencia

**Archivos:** `app/services/quality.py:196`, `app/services/document_processing_core.py`

### Estado real
- `DocumentPage.ocr_confidence` = confianza media del motor por página.
- `Document` no tiene `ocr_confidence` persistido. `_quality_score`
  (`quality.py:196`) recalcula: `base = (document.confidence + media_páginas) / 2`,
  penaliza por nº de flags.
- Páginas digitales (PDF con texto) → confianza 1.0 → inflan la media.

### Problema 🟡
Para un documento con 1 página escaneada (confianza 0.4) + 9 páginas digitales
(confianza 1.0), la media es 0.94 → `_quality_score` alto → **auto-aprobado**
aunque la página escaneada sea ilegible. El flag `low_ocr_confidence` sí captura
páginas individuales bajas (`quality.py:64`: ratio ≥ 50%), pero un doc con
solo 1 de 10 páginas mala (ratio 10%) cae en `partial_low_ocr_confidence` y con
score alto puede pasar el umbral de auto-aprobación.

**FIX 7.1:**
- En `_quality_score`, usar **mínimo** o percentil bajo (p.ej. P25) de las
  confianzas de página, no la media. Una página ilegible debe penalizar siempre.
- O mantener la media pero sumar penalización explícita por página con
  `confidence < threshold`.
- **Aceptación:** un doc 9×digital + 1×scan-malo baja de "auto-aprobado" a
  "needs_review".

---

## Resumen de prioridades

| # | Fix | Categoría | Impacto | Esfuerzo | Riesgo |
|---|-----|-----------|---------|----------|--------|
| 1.1 | Métrica + calibrar `_looks_like_scan` | Confianza | 🔴 Alto | Medio | Bajo |
| 1.2 | PP-Structure vía `preprocess_adaptive` | Velocidad | 🟠 Medio | Bajo | Bajo |
| 1.3 | Cachear OSD/deskew/decisión (no por motor) | Velocidad | 🔴 Alto | Medio | Medio |
| 1.4 | Reintento Tesseract path opuesto | Confianza | 🟡 Medio | Bajo | Bajo |
| 2.1 | `_try_tier3` por `_quality`, no `min_chars` | Confianza | 🟠 Medio | Trivial | Bajo |
| 2.2 | Tier 4 con `confidence=None` | Confianza | 🟡 Bajo | Bajo | Bajo |
| **3.1** | **Paralelismo de páginas** | **Velocidad** | 🔴 Alto | Alto | Alto |
| 4.1 | Subir `_DPI_MIN_CONFIDENCE` a 0.55 | Confianza | 🟠 Medio | Trivial | Bajo |
| 5.1 | Abortar worker si preload falla | Carga | 🟠 Medio | Bajo | Medio |
| 5.2 | Check GPU sin depender de torch | Carga | 🟡 Bajo | Bajo | Bajo |
| 6.1 | Temps en tmpdir + job limpieza | Carga | 🟡 Bajo | Bajo | Bajo |
| 6.2 | `HF_HOME` configurable | Carga | 🟡 Bajo | Trivial | Bajo |
| 7.1 | `_quality_score` por mínimo/P25, no media | Confianza | 🟠 Medio | Bajo | Medio |

### Orden recomendado
1. **Trivial + alto valor:** 2.1, 4.1, 6.2 (1 línea cada uno, sin riesgo).
2. **Confianza:** 1.1 (métrica primero, calibrar después con datos), 7.1.
3. **Velocidad (CPU):** 1.3 + 1.2 (cachear OSD/deskew entre motores). Gran
   ganancia en latencia por página, riesgo medio.
4. **Velocidad (GPU):** 3.1 (paralelismo de páginas) — mayor impacto en PDFs
   multipágina, pero requiere resolver el estado compartido
   (`current_language`, `_preprocess_cache`). Hacer después de 1.3.
5. **Robustez:** 5.1, 5.2, 6.1.

## Verificación global
- [ ] Métrica `preprocess_path_chosen` expuesta y con datos reales.
- [ ] OSD se ejecuta 1× por página (no 2-3×) — test de instrumentación.
- [ ] PP-Structure usa caché de preprocesado (no recomputa).
- [ ] `_try_tier3` decide por `_quality`, sin filtro `min_chars`.
- [ ] PDF de 20 páginas procesa en <50% del tiempo con paralelismo=2.
- [ ] Doc 9×digital + 1×scan-malo no se auto-aprueba.
- [ ] No quedan temps huérfanos tras matar un worker.
- [ ] Tests existentes en verde + tests nuevos por fix.
