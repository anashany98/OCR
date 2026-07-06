# Brief de remediación — docu-intel

> **Para una IA ejecutora sencilla.** Este documento es autocontenido: no necesitas
> auditar el código, solo aplicar las correcciones en orden. Cada tarea tiene
> **Ubicación**, **Problema**, **Cambio exacto** y **Aceptación verificable**.
>
> Trabaja en la rama actual (`feature/nuextract3-integration`) o crea una nueva.
> **Un commit por tarea** con prefijo del ID (`C1`, `M6`, ...). No rompas la
> interfaz pública (`BaseOCREngine.extract`, `embed_many`, `search_*`).
> Tras cada cambio: añade/actualiza tests y mantén la suite en verde
> (`cd docu-intel/backend && pytest -x`).
>
> **Scope prohibido** (no tocar en esta tanda, por `AGENTS.md §0`):
> hardening multi-tenant, rate-limiting, rotación de secretos.
> La tarea **C6** queda *documentada* pero *no se implementa*.

---

## Reglas generales

1. Lee el archivo completo antes de editar. Aplica `Edit` con contexto único.
2. No añadas dependencias nuevas sin añadirlas a `requirements.txt` y al `Dockerfile`.
3. Cada motor OCR sigue **stateless por página**. No introduzcas estado global.
4. Respeta la política "sin hash fallback silencioso" en embeddings.
5. Si un cambio toca migraciones: crea nueva migración Alembic (no edites las existentes).
6. Estilo: comenta lo mínimo, en español, imitando la densidad del código circundante.

---

# BLOQUE C — CRÍTICOS (funcionalidad rota / riesgo alto)

---

## C1 · Fuga de hilos en `pp_structure.py`

**Ubicación:** `docu-intel/backend/app/ocr/pp_structure.py:80-106` (método `extract`).

**Problema:** El `predict()` de PP-Structure se ejecuta en un `threading.Thread(daemon=True)` con `worker.join(timeout=120)`. Si vence el timeout, **el hilo sigue vivo** cargando modelo / consumiendo VRAM. Cada página colgada deja un hilo huérfano. El motor `paddle.py` ya corrigió este antipatrón.

**Cambio exacto:**

1. Sustituye el patrón de `threading.Thread` + `worker.join(timeout=120)` por un `ThreadPoolExecutor(max_workers=1)` desechable con `future.result(timeout=120)`, capturando `concurrent.futures.TimeoutError`.

2. Estructura objetivo (adapta nombres de variables existentes):

```python
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

def extract(self, image_path: Path) -> OCRResult:
    tmp_path = preprocess_adaptive(image_path, engine=self.name)
    exc_holder: list[Exception] = []
    result_holder: list = []

    def _run_predict():
        try:
            result_holder.append(self._pipeline.predict(tmp_path))
        except Exception as e:  # noqa: BLE001
            exc_holder.append(e)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run_predict)
            try:
                future.result(timeout=120)
            except FuturesTimeout:
                future.cancel()
                raise TimeoutError(
                    "PP-Structure predict excedió 120s"
                )
    except Exception as e:  # noqa: BLE001
        # propagar como fallo de tier (lo captura el cascading)
        raise
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    if exc_holder:
        raise exc_holder[0]
    raw = result_holder[0] if result_holder else None
    # ...resto del parseo existente...
```

> Nota: `future.cancel()` no interrumpe un hilo ya corriendo, pero el
> `ThreadPoolExecutor` (bloque `with`) se limpia y el hilo se marca para
> descarte. Esto replica el patrón de `paddle.py:130-152`. Documenta en un
> comentario que el hilo C colgado podría seguir hasta liberar el GIL, igual
> que en paddle.

**Aceptación:**

- [ ] Test `tests/test_pp_structure_timeout.py`: mockea `_pipeline.predict` para dormir >120s, verifica que `extract` lanza `TimeoutError` y que **no** crea un nuevo `threading.Thread` acumulado (cuenta `threading.active_count()` antes/después de N llamadas consecutivas → no crece).
- [ ] `pytest -x tests/test_pp_structure_timeout.py` verde.

---

## C2 · Confianza inventada `0.8` en `dots_mocr.py`

**Ubicación:** `docu-intel/backend/app/ocr/dots_mocr.py:197`.

**Problema:** `confidence=confidence or 0.8`. El endpoint VLM casi nunca devuelve score → DotsMOCR siempre puntúa con 0.8, **mayor** que el default 0.5 que aplica `_quality()` (`cascading.py:60`) para Tesseract/Paddle cuando `confidence=None`. Sesgo sistemático hacia Tier 4.

**Cambio exacto:**

1. Reemplaza la línea por:
   ```python
   confidence=None  # el endpoint VLM-OCR no aporta score fiable
   ```

2. En `cascading.py:_try_tier4` (alrededor de `cascading.py:329`), aumenta el umbral de mejora que Tier 4 debe superar para ganar. Añade una constante:

   ```python
   # Tier 4 (VLM-OCR) es menos fiable: exige mejora más clara
   TIER4_QUALITY_DELTA = 0.15
   ```

   Y en la comparación `_is_better` para Tier 4, exige
   `_quality(tier4) > _quality(best_prior) + TIER4_QUALITY_DELTA`
   (en vez del `QUALITY_EPSILON = 0.01`).

**Aceptación:**

- [ ] Test `tests/test_cascading_tier4_bias.py`: dado un Tier 1 con texto limpio y confianza 0.6, y un Tier 4 con texto de longitud similar pero confianza None, Tier 1 **gana** (antes Tier 4 ganaba por el 0.8).

---

## C3 · Escalas incommensurables en `_quality`

**Ubicación:** `docu-intel/backend/app/ocr/cascading.py:54-63`.

**Problema:** `_quality` mezcla `confidence` (Tesseract 0-1 real, PP-Structure siempre None→0.5, DotsMOCR None tras C2). La ponderación `0.5·conf + 0.3·density + 0.2·length` queda sesgada hacia quien tiene `confidence=None`.

**Cambio exacto:**

1. Documenta que la confianza se **normaliza** a un rango comparable. Cuando `confidence is None`, usa `0.5` (ya hace esto L60 — mantenerlo, pero **comentar** que es un neutral deliberado, no un bug).

2. Reduce el peso de `confidence` y sube `density` (la densidad alfanumérica es la señal más fiable entre motores heterogéneos):

   ```python
   def _quality(result: OCRResult) -> float:
       text = (result.text or "").strip()
       if not text:
           return 0.0
       alnum = _alnum_count(text)
       density = alnum / max(len(text), 1)
       conf = result.confidence if result.confidence is not None else 0.5
       length_factor = min(len(text) / 500.0, 1.0)
       # densidad es la señal más fiable entre motores heterogéneos
       return conf * 0.4 + density * 0.4 + length_factor * 0.2
   ```

3. Añade test que verifique que tras C2+C3, una salida Tesseract limpia
   (densidad 0.9, conf 0.6) puntúa **mayor** que una salida DotsMOCR ruidosa
   (densidad 0.4, conf None→0.5) aunque esta última sea más larga.

**Aceptación:**

- [ ] `tests/test_cascading_quality.py` cubre los 3 casos: texto símbolico largo vs texto limpio corto, confianza None vs real, normalización.

---

## C4 · Rama "photo → vision LLM" compara por longitud

**Ubicación:** `docu-intel/backend/app/ocr/cascading.py:214-223`.

**Problema:** `if len(vision_text) > len(ocr_text)` contradice la filosofía del cascade (que manda `_quality`). Una vision LLM que devuelve 60 chars de basura gana a 40 chars correctos.

**Cambio exacto:**

1. Reemplaza la comparación por longitud por una por `_quality`:

   ```python
   # antes: if len(vision_text) > len(ocr_text):
   if _quality(vision_result) > _quality(ocr_result) + QUALITY_EPSILON:
       return self._finalize(image_path, vision_name, vision_result)
   return self._finalize(image_path, self.primary.name, ocr_result)
   ```

   (Adapta los nombres reales de variables según el código existente.)

**Aceptación:**

- [ ] Test `tests/test_cascading_photo_branch.py`: mockea vision LLM devolviendo `"!@# $%^ &*()"` (60 chars, baja densidad) y OCR devolviendo `"Factura 2024"` (12 chars, alta densidad) → OCR gana.

---

## C5 · Coerción silenciosa de dimensión de embedding

**Ubicación:** `docu-intel/backend/app/services/embeddings.py:705-717`
(función `coerce_embedding_dimensions`).

**Problema:** Si `EMBEDDING_ALLOW_DIMENSION_COERCION=true`, vectores más cortos se **rellenan con ceros** y más largos se **truncan** — vectores corruptos sin error. Riesgo real si el flag queda activo tras una migración.

**Cambio exacto:**

1. Mantén el comportamiento de error cuando el flag está apagado (líneas 709-714).

2. Cuando el flag está activo (líneas 715-717), añade logging WARNING + métrica
   **por cada vector coaccionado**, y documenta que es solo para migración:

   ```python
   else:
       # Solo para migración: nunca dejar activo en producción.
       logger.warning(
           "Embedding coaccionado de %d a %d dims (coercion habilitada). "
           "Esto corrompe la similitud — apaga EMBEDDING_ALLOW_DIMENSION_COERCION.",
           len(values), expected,
       )
       if hasattr(... "track_embedding_coercion"):  # si existe módulo métricas
           track_embedding_coercion(len(values), expected)
       if len(values) < expected:
           return list(values) + [0.0] * (expected - len(values))
       return list(values[:expected])
   ```

3. En `app/core/config.py`, añade validación: si el flag está activo y no es
   entorno de migración explícito, lanza warning al arranque:

   ```python
   @validator("embedding_allow_dimension_coercion")
   def _warn_coercion(cls, v, values):
       if v:
           # pragma: no cover
           import warnings
           warnings.warn(
               "EMBEDDING_ALLOW_DIMENSION_COERCION activo: vectores pueden "
               "corromperse. Solo para migración.",
               stacklevel=2,
           )
       return v
   ```

**Aceptación:**

- [ ] Test `tests/test_embedding_coercion.py`: con flag activo, un vector de 512 dims se coacciona a 768 y se loguea WARNING (captura con `caplog`). Con flag apagado, lanza `ValueError`.

---

## C6 · Agregaciones de facturas sin filtrado de alcance ⚠️ NO IMPLEMENTAR

**Ubicación:** `docu-intel/backend/app/api/routes/invoices.py:101,129,156`.

**Problema:** Los endpoints `/aggregate/monthly`, `/aggregate/by-supplier`,
`/aggregate/yearly` no aplican `apply_access_predicates`. Un usuario no-admin
puede ver totales de documentos a los que no tiene acceso.

**Acción:** **Documentado pero NO se implementa en esta tanda** (fuera de scope
según `AGENTS.md §0`: "no multi-tenant hardening"). Queda registrado para tanda
de seguridad posterior. **No escribas código para C6.**

**Si el humano lo pide explícitamente más adelante**, la solución es: en cada
uno de los tres agregados, llamar `resolve_user_access_scope(db, current_user)`
y `apply_access_predicates(stmt, scope)` antes de ejecutar la query, igual que
en `list_invoices:45`.

---

## C7 · `Invoice.date` declarado como `Any`

**Ubicación:** `docu-intel/backend/app/models/professional.py:140`.

**Problema:** `date: Mapped[Any | None] = mapped_column(Date)`. Debería ser
`date` (de `datetime`). El schema `InvoiceRead` lo declara como `date`, así que
hay incoherencia.

**Cambio exacto:**

1. Verifica el import existente de `date`:
   ```python
   from datetime import date as date_type, datetime
   ```
   (u otro alias usado en el archivo).

2. Reemplaza la línea:
   ```python
   # antes: date: Mapped[Any | None] = mapped_column(Date)
   date: Mapped[date_type | None] = mapped_column(Date)
   ```

3. Si `Any` era un parche para evitar un import circular, **no** — `date` del
   stdlib no crea ciclos. Elimina el `Any` del typing.

**Aceptación:**

- [ ] `pytest tests/test_business_extraction.py` verde.
- [ ] `mypy app/models/professional.py` (si está configurado) no reporta error en esa línea.

---

## C8 · Acciones en lote destructivas sin confirmación

**Ubicación:** `docu-intel/frontend/src/pages/work-inbox/WorkInboxPage.tsx:96-105`
y `src/pages/work-inbox/components.tsx:566-595`.

**Problema:** `retry_failed_jobs`, `approve_high_confidence_ocr`,
`reprocess_low_quality` se disparan con un clic, sin confirmación.
`approve_high_confidence_ocr` puede aprobar hasta 200 OCR sin revisión humana.

**Cambio exacto:**

1. Si existe componente `AlertDialog`/`ConfirmDialog` en
   `frontend/src/components/ui/`, úsalo. Si no, crea
   `src/components/ui/ConfirmDialog.tsx` accesible
   (role="alertdialog", focus trap, ESC para cancelar).

2. En `BatchActionsCard` (`components.tsx`), envuelve el `onAction`:

   ```tsx
   const [pending, setPending] = useState<BatchActionId | null>(null);

   const handleAction = (id: BatchActionId) => setPending(id);
   const confirm = () => {
     if (pending) onAction(pending);
     setPending(null);
   };

   // botones llaman a handleAction(id) en vez de onAction(id)

   <ConfirmDialog
     open={pending !== null}
     title="Confirmar acción en lote"
     description={`Se ejecutará "${labelFor(pending)}". Esta acción puede afectar a muchos documentos y no es reversible.`}
     confirmLabel="Ejecutar"
     cancelLabel="Cancelar"
     onConfirm={confirm}
     onCancel={() => setPending(null)}
   />
   ```

**Aceptación:**

- [ ] Al clic en cualquier acción de lote aparece el diálogo; solo al confirmar se ejecuta la mutación.
- [ ] El diálogo es cerrable con ESC y con foco accesible (verifica con tab).
- [ ] `npm run build` (en `frontend/`) verde.

---

# BLOQUE M — MEDIOS (degradación / fragilidad)

> Aplica estos en orden. Cada uno es commit independiente.

---

## M1 · Doble cacheo incoherente en `factory.py`

**Ubicación:** `docu-intel/backend/app/ocr/factory.py:30,34,118-122`.

**Problema:** `_engine_singleton` (global) coexiste con `@lru_cache` en
`get_ocr_engine_class`. `clear_ocr_engine_cache()` limpia ambos, pero tests
que parchean sin llamarla quedan stale.

**Cambio exacto:**

1. Elimina el `@lru_cache(maxsize=1)` de `get_ocr_engine_class` y gestiónalo
   con una variable `_engine_class_singleton` paralela, limpiada por
   `clear_ocr_engine_cache`.

2. `clear_ocr_engine_cache` debe resetear `_engine_singleton`,
   `_engine_class_singleton` y llamar `gc.collect()` opcional.

**Aceptación:**

- [ ] Test: parchea `get_ocr_engine_class`, llama a `clear_ocr_engine_cache`, siguiente `get_ocr_engine()` usa la clase parcheada.

---

## M2 · `_CascadingFactory.__new__` hack

**Ubicación:** `docu-intel/backend/app/ocr/factory.py:69-75`.

**Problema:** `__new__` devuelve otra cosa que una instancia de la clase
(`# type: ignore[return-value]`). Rompe `isinstance` y confunde a type checkers.

**Cambio exacto:**

1. Convierte `_CascadingFactory` en función `get_cascading_engine()` clara.
2. Actualiza los callers que usen `_CascadingFactory()` a `get_cascading_engine()`.

**Aceptación:**

- [ ] No queda `type: ignore[return-value]` en factory.
- [ ] `pytest tests/ -k ocr` verde.

---

## M3 · `_warm_ocr_engine` sin timeout

**Ubicación:** `docu-intel/backend/app/ocr/factory.py:219-231`.

**Problema:** Si el init del modelo cuelga, mata el worker Celery en
`worker_process_init`.

**Cambio exacto:**

1. Envuelve el warmup en un `ThreadPoolExecutor(max_workers=1)` con
   `future.result(timeout=settings.ocr_engine_warmup_timeout)` (añadir setting,
   default 180s).

2. Si vence el timeout, loguea ERROR, marca el motor como no disponible y deja
   que el worker arranque (mejor degradado que muerto).

**Aceptación:**

- [ ] Test: mockea init que duerme infinito → worker no crashea, motor queda no disponible.

---

## M4 · Pesos RRF declarados pero no aplicados

**Ubicación:** `docu-intel/backend/app/services/bm25.py:66-70,446-479`
y `app/services/search_service.py:608-650`.

**Problema:** `DEFAULT_WEIGHTS`/`adaptive_weights` existen pero
`merge_hybrid_results` no los usa — todas las estrategias contribuyen 1.0 por
rango. Código muerto.

**Cambio exacto (decide una de dos opciones y documéntala):**

- **Opción A (recomendada, simple):** eliminar `DEFAULT_WEIGHTS` y
  `adaptive_weights` de `bm25.py` si no se van a usar. RRF puro ya es robusto.

- **Opción B (potencia):** aplicar pesos en `merge_hybrid_results`:
  ```python
  weight = STRATEGY_WEIGHTS.get(r.strategy, 1.0)
  scores[key] += weight / (k + rank + 1)
  ```
  y conectar `adaptive_weights` (decisión por longitud de query / presencia de
  números).

**Aceptación:**

- [ ] No hay código muerto (Opción A) o los pesos afectan el ranking (Opción B, con test).
- [ ] `pytest tests/test_local_embedding_reranker.py` verde.

---

## M5 · Asimetría query/passage solo para ST local

**Ubicación:** `docu-intel/backend/app/services/embeddings.py:226-227`.

**Problema:** `embed_query_text` cae a modo passage para openai_compatible.
Si se conecta un modelo asimétrico (BGE/E5/text-embedding-3), no recibe el
prefijo.

**Cambio exacto:**

1. Añade setting `embedding_query_instruction: str | None` y
   `embedding_passage_instruction: str | None` en `config.py`.

2. En el path openai_compatible de `embed_query_text`, si hay setting, pásalo
   como `extra_body={"prompt": instruction}` (API OpenAI) o como prefijo
   manual para servidores compatibles que no soporten `prompt`.

**Aceptación:**

- [ ] Test: con setting activo, la request HTTP incluye la instrucción.

---

## M6 · `_parse_amount` hardcode es-ES

**Ubicación:** `docu-intel/backend/app/services/business_extraction.py:1298-1366`.

**Problema:** Locale `es-ES` fijo. `"1.234"` siempre → 1234 (miles). Proveedores
EN se malinterpretan.

**Cambio exacto:**

1. Extrae detección de locale por contexto: si el documento o el proveedor
   sugieren formato EN (uppercase country code, idioma detectado `en`), usar
   formato EN; si no, es-ES.

2. Reutiliza la lógica robusta de `plan_extraction._parse_number` (que ya
   distingue ES/EN por regex con `has_unit`) — o impórtala y úsala.

**Aceptación:**

- [ ] Tests paramétricos:
  - `"1.234"` con locale es-ES → 1234.0
  - `"1.234"` con locale en → 1.234
  - `"1.234,56"` es-ES → 1234.56
  - `"1,234.56"` en → 1234.56

---

## M7 · `polygon_json` siempre None

**Ubicación:** `docu-intel/backend/app/services/plan_extraction.py:619`.

**Problema:** `polygon_json` nunca se llena. `width_m`/`length_m` solo vía
`ROOM_DIMENSION_PAIR_RE`.

**Cambio exacto:**

1. Cuando una estancia tenga bbox y `scale_ratio` válida, deriva
   `polygon_json` (rectángulo del bbox en metros) y completa
   `width_m`/`length_m` desde el bbox convertido.

2. Valida coherencia con `area_m2` impresa si existe (±15%).

**Aceptación:**

- [ ] Test: estancia con bbox y escala 1:100 → `polygon_json` no None,
  `width_m`/`length_m` coherentes con el bbox.

---

## M8 · `_load_plan_page_dpi` dead code

**Ubicación:** `docu-intel/backend/app/services/plan_extraction.py:670-692`.

**Problema:** Dos `return settings.pdf_ocr_dpi` idénticos (rama muerta).

**Cambio exacto:**

1. Deriva el DPI real del render si está disponible en metadatos del
   documento/página; si no, devuelve `settings.pdf_ocr_dpi` con un solo
   `return` y comentario explicando el fallback.

**Aceptación:**

- [ ] No queda rama muerta; test existente verde.

---

## M9 · Validación de escala se salta silenciosamente

**Ubicación:** `docu-intel/backend/app/services/plan_extraction.py:770-772`.

**Problema:** `_validate_dimensions_against_scale` se aborta sin avisar cuando
`bbox is None`.

**Cambio exacto:**

1. Añade `logger.debug("No se puede validar cota: bbox ausente")` y una métrica
   `track_plan_validation_skipped(reason="no_bbox")`.

**Aceptación:**

- [ ] Con `caplog` se verifica el mensaje cuando no hay bbox.

---

## M10 · Umbral OCR "dudoso" bajado a 0.60

**Ubicación:** `docu-intel/backend/app/ai/context.py:107`.

**Problema:** `LOW_OCR_CONFIDENCE_THRESHOLD = 0.60` (AGENTS.md A7 pide 0.70).
Reduce sensibilidad para detectar OCR mediocre.

**Cambio exacto:**

1. Restablece a `0.70` **o** hazlo configurable via setting
   `ai_low_ocr_confidence_threshold: float = 0.70` y úsalo.

2. Comprueba que el marcador `[OCR DUDOSO]` sigue inyectándose correctamente.

**Aceptación:**

- [ ] Test: un chunk con confianza 0.65 queda marcado como dudoso (antes no).

---

## M11 · Sin job de re-OCR + re-embed automático

**Ubicación:** nueva tarea Celery en `app/workers/celery_app.py`.

**Problema:** Solo hay sugerencia manual al usuario (`context.py:1042-1056`).
AGENTS.md A7 pide un job que re-procese documentos con `needs_reembedding` /
baja confianza cuando el OCR mejore.

**Cambio exacto:**

1. Añade tarea `reprocess_low_confidence_documents` registrada en el beat
   schedule (diaria).

2. Selección: documentos donde `needs_reembedding=True` o
   `OCR_CONFIDENCE < settings.ai_low_ocr_confidence_threshold` en sus páginas.

3. Re-ejecuta el pipeline de OCR + re-embebedo; respeta concurrencia GPU.

**Aceptación:**

- [ ] Test con fixture: documento marcado `needs_reembedding` → tras el job,
  flag reseteado y nuevos chunks generados.

---

## M12 · Cache de búsqueda sin invalidación

**Ubicación:** `docu-intel/backend/app/services/search_service.py:27,425-428`.

**Problema:** Cache (TTL 300s) no se invalida al reindexar. Tras re-embed,
sirve resultados obsoletos.

**Cambio exacto:**

1. Cuando `reembed_document` (en `embeddings.py:732`) corre, invalida las
   claves de cache de búsqueda asociadas al `document_id`. Si la cache es
   por query, añade un versionado por `document_embedding_version` (columna
   nueva o counter en memoria).

2. Alternativa simple: reducir TTL a 60s y documentarlo.

**Aceptación:**

- [ ] Test: re-embed un documento → siguiente búsqueda no sirve cache viejo.

---

## M13 · `list_invoices` ejecuta query dos veces

**Ubicación:** `docu-intel/backend/app/api/routes/invoices.py:37-54`.

**Problema:** Primero `db.scalars(stmt.limit(limit))` (L37), luego si no es
admin reescribe `stmt` y vuelve a ejecutar (L46). Primera ejecución
desperdiciada.

**Cambio exacto:**

1. Mueve la comprobación `scope.is_admin` **antes** del primer `db.scalars`:

   ```python
   scope = resolve_user_access_scope(db, current_user)
   if not scope.is_admin:
       stmt = apply_access_predicates(stmt, scope)
   invoices = db.scalars(stmt.limit(limit)).all()
   return [InvoiceRead.model_validate(i) for i in invoices]
   ```

**Aceptación:**

- [ ] Test: para usuario no-admin, la query SQL se ejecuta una sola vez
  (verifica con `db.execute` espiado o `connection.queries` en SQLite).

---

## M14 · `pdf_ocr_dpi` ignorado por el parser

**Ubicación:** `docu-intel/backend/app/parsers/pdf.py:257` vs
`app/core/config.py:426`.

**Problema:** DPI ladder `[300,400,600]` hardcoded. Operador que sube
`PDF_OCR_DPI=400` no obtiene efecto.

**Cambio exacto:**

1. Construye el ladder dinámicamente:
   ```python
   _BASE_DPI = settings.pdf_ocr_dpi
   _DPI_LADDER = [_BASE_DPI, _BASE_DPI + 100, _BASE_DPI + 300]
   ```

2. Asegura que `_BASE_DPI` sea legible (lee `settings` dentro de una función,
   no a nivel módulo, para tests que parcheen settings).

**Aceptación:**

- [ ] Test: con `PDF_OCR_DPI=400`, el primer peldaño del ladder es 400.

---

## M15 · `Vector(768)` hardcoded en modelo

**Ubicación:** `docu-intel/backend/app/models/document.py:222` vs
`app/core/config.py:259`.

**Problema:** Cambiar `EMBEDDING_DIMENSIONS` no se refleja en el modelo ORM.

**Cambio exacto:**

1. Documenta en `config.py` que cambiar el setting requiere migración manual
   `ALTER COLUMN ... TYPE VECTOR(1536)` y rebuild del índice.

2. (Opcional, más avanzado) Lee la dimensión vía `settings.embedding_dimensions`
   en un `__table_args__` dinámico — cuidado, esto rompe migraciones
   autogeneradas. **Recomendado: solo documentar.**

**Aceptación:**

- [ ] Comentario en `config.py:259` y `document.py:222` explicando la
  dependencia y el procedimiento de migración.

---

## M16 · Worker GPU sin `WORKER_NAME` arranca sin precarga

**Ubicación:** `docu-intel/backend/app/workers/celery_app.py:106-112`.

**Problema:** Despliegue bare-metal sin `WORKER_NAME=...heavy...` arranca sin
precarga OCR (silencioso).

**Cambio exacto:**

1. Loguea WARNING al arranque si `settings.worker_name` no contiene "heavy"/"ocr"
   pero `CUDA_VISIBLE_DEVICES` está seteado:
   ```python
   if "heavy" not in (settings.worker_name or "") and os.environ.get("CUDA_VISIBLE_DEVICES"):
       logger.warning("GPU visible pero WORKER_NAME no indica worker heavy; "
                      "no se precargará el motor OCR en arranque.")
   ```

**Aceptación:**

- [ ] Test de arranque (mock) verifica el warning con `caplog`.

---

## M17 · `dots_mocr.py` crash si respuesta no es dict

**Ubicación:** `docu-intel/backend/app/ocr/dots_mocr.py:184-191`.

**Problema:** Si la respuesta es una lista u otro tipo, `data.get` lanza
`AttributeError` no capturada.

**Cambio exacto:**

1. Envuelve:
   ```python
   if not isinstance(data, dict):
       raise ValueError(f"Respuesta VLM-OCR inesperada: {type(data).__name__}")
   ```

**Aceptación:**

- [ ] Test: mock que devuelve `[{"text": "x"}]` → `ValueError` claro, no crash.

---

## M18 · `looks_like_followup` frágil

**Ubicación:** `docu-intel/backend/app/ai/validation.py:698-796`.

**Problema:** Lista manual `_FOLLOWUP_HINTS`; no cubre "¿y este otro?" sin
pronombre listado.

**Cambio exacto:**

1. Amplía la lista con: `"este"`, `"ese"`, `"aquel"`, `"otro"`, `"mismo"`,
   `"también"`, `"y el"`, `"y la"`, `"siguiente"`.

2. (Más robusto) Alternativa: inyectar siempre las últimas N respuestas del
   documento como contexto y dejar que el LLM desambigüe.

**Aceptación:**

- [ ] Test: "¿y este otro?" tras una consulta → se considera follow-up.

---

## M19 · Vision client menos robusto que chat

**Ubicación:** `docu-intel/backend/app/ai/local_client.py:477-551`.

**Problema:** `LocalVisionClient.describe` reintenta solo en 5xx, no en
429/timeout. Reimplementa retry.

**Cambio exacto:**

1. Extrae el helper de retry/backoff del path de chat a una función
   `_request_with_retry(client, method, url, **kwargs)` compartida.

2. Úsala tanto en `chat` como en `describe` con la misma política
   (`_is_retryable_ai_error`: 429/5xx/timeout/transport).

**Aceptación:**

- [ ] Test: vision con 429 simulado → reintenta con backoff.

---

## M20 · Polling sin `refetchIntervalInBackground`

**Ubicación:** `docu-intel/frontend/src/components/layout/AppShell.tsx:28`,
`src/pages/admin/useAdminSystemData.ts:31-41`, y similares.

**Problema:** Polling cada 30s sigue en pestaña oculta. Coste de red/batería.

**Cambio exacto:**

1. Añade `refetchIntervalInBackground: false` a todas las queries con
   `refetchInterval`.

2. (Opcional) Crea un wrapper `usePollingQuery` que aplique el flag por defecto.

**Aceptación:**

- [ ] En pestaña oculta (simula con `document.visibilityState="hidden"`), no
  hay requests (verifica con mocks de fetch).

---

## M21 · `<Badge>` clickeable no accesible

**Ubicación:** `docu-intel/frontend/src/components/layout/AppShell.tsx:96-107`.

**Problema:** `<span onClick>` no es enfocable ni anunciado como control.

**Cambio exacto:**

1. Reemplaza el `<span>` por `<button>` con `onClick`, estilos de botón reset
   (`className="appearance-none ..."`), manteniendo el look de badge.

2. Asegura `aria-label` descriptivo.

**Aceptación:**

- [ ] Tab llega al badge, Enter activa, lector de pantalla anuncia "botón".

---

## M22 · `AdminDashboardPage.tsx` dead code

**Ubicación:** `docu-intel/frontend/src/pages/admin/AdminDashboardPage.tsx`.

**Problema:** 428 líneas no referenciadas en router ni en `src/`.

**Cambio exacto:**

1. Verifica con `grep -r "AdminDashboardPage" frontend/src` que no hay
   importadores.

2. Elimina el archivo.

**Aceptación:**

- [ ] `npm run build` verde tras eliminar.

---

## M23 · `created_at` divergente en delivery_notes

**Ubicación:** migración `0041_delivery_notes.py:42` vs
`app/models/business.py:121`.

**Problema:** Migración usa `server_default=func.now()`, modelo usa
`default=lambda: datetime.now(UTC)`.

**Cambio exacto:**

1. Unifica: aplica **ambos** en el modelo:
   ```python
   created_at: Mapped[datetime] = mapped_column(
       DateTime(timezone=True),
       default=lambda: datetime.now(UTC),
       server_default=func.now(),
   )
   ```

2. Comprueba que las otras tablas nuevas siguen el mismo patrón.

**Aceptación:**

- [ ] Inserción vía ORM y vía SQL crudo producen timestamps consistentes.

---

# BLOQUE B — BAJOS (pulido)

> Tareas pequeñas, agrúpables en un commit `chore: cleanup low-severity`.

- **B1:** `search.py:39,57,133,248,329` — añade `max_length=500` a los
  `Query(min_length=1)` de `q`.
- **B2:** `document.py:63,67` — añade `index=True` a
  `duplicate_of_document_id` y `deleted_by_id` (migración nueva).
- **B3:** `docker-compose.yml:299` — mueve el bind mount Windows absoluto a un
  override `docker-compose.dev.yml` o bórralo del compose base.
- **B4:** `preprocess.py:124` — elimina `preprocess_for_ocr` (dead alias).
- **B5:** `tesseract.py:28`, `paddle.py:29` — elimina imports muertos
  (`preprocess_for_tesseract`, `preprocess_for_paddle`).
- **B6:** `paddle.py:32` — reemplaza `__import__("logging")` por `import logging`.
- **B7:** `pp_structure.py:36` — mueve el `os.environ.setdefault` dentro de una
  función de init, no a nivel módulo.
- **B8:** `tesseract.py:94` — `avg_conf` ponderada por longitud de línea.
- **B9:** `plan_extraction.py` — `_looks_like_plan`: añade `m²` unicode al
  patrón `\bm\s*2\b`.
- **B10:** `classification.py:33` — retira "cliente" de
  `RULES["presupuesto"]` o bájale peso.
- **B11:** `requirements.txt` — pinnar `sentence-transformers<4` y `xlrd<3`.
- **B12:** `tests/test_ai_chat_real.py` y `tests/test_e2e_demo.py` — son
  demos `if __name__=="__main__"`. Mueve a `scripts/` o renombra sin prefijo
  `test_` (pytest los descubre e intenta importar).
- **B13:** `navigation/config.ts` — ruta `/admin/calidad` duplicada
  (Duplicados vs Cuarentena). Usa paths distintos o fusiona.
- **B14:** `ErrorBoundary.tsx:45,57` — reemplaza `bg-red-50` por tokens
  `var(--danger-*)`; oculta `error.message` salvo dev.
- **B15:** `AppShell.tsx:151-165` — menú de usuario sin acción: implementa
  logout/settings o elimínalo.
- **B16:** `router.tsx:16-17` — deriva `ADMIN_ROLES`/`MANAGER_ROLES` desde
  `NAV_GROUPS`.
- **B17:** `pdf.py:244` — `_run_coro_sync`: añade timeout al `thread.join`.

---

# Checklist global de aceptación

- [ ] Suite existente verde: `cd docu-intel/backend && pytest -x`.
- [ ] Frontend build verde: `cd docu-intel/frontend && npm run build`.
- [ ] Cada tarea con su commit (`C1`, `M6`, ...) y su test.
- [ ] No se han añadido dependencias nuevas sin `requirements.txt` + `Dockerfile`.
- [ ] No se ha roto la interfaz `BaseOCREngine.extract` ni `embed_many`/`search_*`.
- [ ] No se ha tocado multi-tenant/rate-limit/secrets (salvo C6, que queda
      solo documentado).
- [ ] `mypy`/`ruff` (si están configurados) no reportan nuevos errores.

---

# Orden de ejecución recomendado

| # | Tarea | Impacto | Esfuerzo |
|---|-------|---------|----------|
| 1 | **C1** — fuga hilos PP-Structure | Estabilidad | M |
| 2 | **C2 + C3 + C4** — confianza `_quality` cascade | Precisión OCR | M |
| 3 | **C5** — coerción silenciosa embeddings | Integridad índice | B |
| 4 | **C7** — tipo `Invoice.date` | Tipado | B |
| 5 | **C8** — confirmación lotes frontend | UX/seguridad | B |
| 6 | **M6 + M14** — locale amount, DPI setting | Precisión extracción | M |
| 7 | **M10 + M11 + M12** — cierra bloque A (umbral, re-embed, cache) | RAG | M |
| 8 | **M13 + M15 + M16** — API/modelos/worker | Correctitud | B |
| 9 | **M4 + M5** — pesos RRF, asimetría openai | Ranking | M |
| 10 | **M1 + M2 + M3** — factory OCR | Mantenibilidad | M |
| 11 | **M7-M9** — planos (polygon, dpi, validación) | Función planos | M |
| 12 | **M17-M19** — robustez IA (VLM, followup, vision retry) | Robustez | M |
| 13 | **M20-M23** — frontend/migraciones | Pulido | B |
| 14 | **Bloque B** — cleanup | Pulido | B |

---

# Notas para la IA ejecutora

- Si un cambio te parece que ya está aplicado (parte de la auditoría encontró
  cosas ya corregidas), **verifícalo leyendo el archivo** antes de tocar. Marca
  la tarea como "ya hecho" en tu reporte y no dupliques trabajo.
- Si una tarea requiere migración: crea `alembic/versions/0042_*.py` con
  `down_revision = "0041_delivery_notes"`.
- Si una línea referenciada no coincide exactamente (el código pudo moverse),
  busca por contenido, no por número de línea.
- **No hagas C6** salvo instrucción explícita posterior.
- Tras cada commit, ejecuta los tests del módulo afectado antes de pasar al
  siguiente.
