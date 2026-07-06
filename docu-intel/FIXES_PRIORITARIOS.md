# Brief de trabajo — Fixes prioritarios

> 📌 Este documento es un **brief para una IA de código** (Cursor / Claude Code /
> similar). Cópialo a `docu-intel/AGENTS.md` o pásalo como prompt. Contiene los
> **fixes priorizados a partir de un análisis de la base de datos de producción**
> (PostgreSQL del contenedor `docu-intel-postgres-1`, BD `docuintel`).
>
> Objetivo: **desbloquear los fallos de procesamiento y reducir la cola de
> revisión humana**. Cada tarea es incremental y revisable: **un commit por
> tarea** con prefijo `FIX-N`.
>
> Respeta las reglas del `AGENTS.md` raíz: no romper interfaces, añadir tests,
> cambios incrementales, sin dependencias nuevas sin añadirlas a
> `requirements.txt` y `Dockerfile`.

## Resumen del análisis de BD (contexto)

Estado actual de la BD (2026-07-01):

| Estado documento | Count |
|------------------|-------|
| `needs_review`   | 1025  |
| `processed`      | 937   |
| `duplicate`      | 293   |
| `pending`        | 193   |
| `processing`     | 46    |
| `failed`         | 0 (a nivel documento) |

**Fallos de jobs**: 45 jobs `extraction_jobs` con `status='failed'`, **todos con
el mismo error**:

```
psycopg.errors.UndefinedColumn: column "project_phase" of relation "plans" does not exist
```

**Motivos mayoritarios en `needs_review`** (por flag individual):

| Flag | Docs |
|------|------|
| `low_ocr_confidence`               | 343 |
| `business_extraction_needs_review` | 292 |
| `page_without_text`                | 229 |
| `document_type_unknown`            | 125 |
| `text_too_short`                   | 82  |
| `budget_number_missing`            | 80  |
| `supplier_missing`                 | 61  |
| `invoice_date_missing`             | 32  |
| `order_number_missing`             | 30  |
| `partial_low_ocr_confidence`       | 21  |
| `security:invalid_*_signature`     | 9   |

**Cadena causal verificada**:

```
preprocesado no aplicado (O1/O2) → OCR con baja confianza
  → low_ocr_confidence (343) + page_without_text (229) + text_too_short (82)
  → text_too_short y campos no detectados (budget/supplier/date missing)
  → business_extraction_needs_review (292)
  → todo termina en needs_review
```

**Conclusión**: arreglar el OCR (O1/O2/O3) reduce en cascada ~675 docs y buena
parte de los flags de negocio. El bug de `plans.project_phase` desbloquea los 45
fallos. El `invoice_date_missing` es un bug de regex aislado y trivial.

---

## FIX-1 · Migración `plans.project_phase` (DESBLOQUEA 45 FALLOS) 🔴

**Archivos**: `docu-intel/backend/app/models/business.py`,
nueva migración Alembic en `docu-intel/backend/alembic/versions/`.

**Problema (verificado en BD)**: El modelo `Plan` define
`project_phase` (`app/models/business.py:128`) como parte del workitem
P5 (multi-sheet association), pero **la tabla `plans` en PostgreSQL no tiene esa
columna**. Esquema real de la tabla:

```
 id | document_id | project_name | scale_text | scale_ratio | scale_confidence
    | unit | has_valid_scale | created_at
```

Resultado: **cualquier documento clasificado como `plano` falla al persistir la
extracción** con `UndefinedColumn: column "project_phase" of relation "plans"
does not exist`. 45 jobs `failed`, `retries=0`, ventana de ~14h de fallos
continuos. Los documentos quedan sin extracción de plano (probablemente en
`needs_review` / `pending`).

**Cambio requerido**:

1. Crear migración Alembic que añada a `plans` las columnas que el modelo
   espera. Revisar `app/models/business.py` entero (clase `Plan`) para detectar
   **todos** los campos del P5 multi-sheet que falten en la tabla
   (`project_phase`, `revision`, `plan_set_id`, etc.). No limitarse a
   `project_phase`.
2. La migración debe ser **idempotente** y segura en producción (usar
   `op.add_column` con `nullable=True` para no romper filas existentes; añadir
   índices solo si el modelo los tiene con `index=True`).
3. Ejecutar la migración contra la BD del contenedor:
   ```bash
   docker exec docu-intel-backend-1 alembic upgrade head
   ```
   (o el comando equivalente usado por el proyecto para migrar).
4. Verificar que el esquema queda sincronizado con el modelo:
   ```bash
   docker exec docu-intel-postgres-1 psql -U app -d docuintel -c "\d plans"
   ```

**Limpieza de datos**: tras la migración, los 45 jobs fallidos NO se reintentan
sólos (`retries=0`). Hay que reencolarlos:

```sql
-- Listar los jobs a reencolar (verificar antes)
SELECT id, document_id FROM extraction_jobs WHERE status='failed'
  AND error_message LIKE '%project_phase%';

-- Reencolar: volver a status='pending' y limpiar error (ejecutar solo si la
-- migración ya está aplicada y el worker sabe retomar jobs pending). Ajustar
-- según el campo real usado por el dispatcher.
UPDATE extraction_jobs
SET status='pending', error_message=NULL, started_at=NULL, finished_at=NULL
WHERE status='failed' AND error_message LIKE '%project_phase%';
```

**Aceptación**:
- [ ] `\d plans` muestra `project_phase` (y el resto de columnas del modelo).
- [ ] Procesar un PDF de plano nuevo no lanza `UndefinedColumn`.
- [ ] Los 45 jobs reencolados pasan a `processed` o fallan por otro motivo
      distinto (no `project_phase`).
- [ ] Test que cree un `Plan` con `project_phase` y verifique que persiste.

---

## FIX-2 · Preprocesado OCR real, específico por motor (O1 + O2) 🔴

**Archivos**: `app/ocr/preprocess.py`, `app/ocr/tesseract.py`,
`app/ocr/paddle.py`, `app/ocr/pp_structure.py`.

**Problema (verificado en BD)**: `preprocess_for_ocr()` existe pero **ningún
motor lo llama**. Esto es la causa raíz de ~675 documentos en `needs_review`
(`low_ocr_confidence` 343 + `page_without_text` 229 + `text_too_short` 82 +
`partial_low_ocr_confidence` 21).

**Matiz crítico**: la binarización adaptativa actual (`adaptiveThreshold`)
**ayuda a Tesseract pero perjudica a PaddleOCR y PP-Structure**, que esperan
imagen en color/gris. El preprocesado debe ser **específico por motor**.

**Cambio requerido**:

1. En `preprocess.py`, reemplazar/añadir dos funciones:
   - `preprocess_for_tesseract(path) -> Path` → gris + denoise (`cv2.fastNlMeansDenoising`) + deskew + binarización adaptativa (`cv2.adaptiveThreshold`) + upscaling ×2 si lado menor < 1500 px.
   - `preprocess_for_paddle(path) -> Path` → solo deskew + upscaling + denoise suave, **sin binarizar**.
2. Implementar `_deskew(gray)` con `cv2.minAreaRect` (pseudocódigo de referencia
   en el `AGENTS.md` raíz, sección O2). No rotar si `abs(angle) < 0.5°` (evita
   rotar por ruido).
3. Orientación: usar `pytesseract.image_to_osd` para detectar rotación de
   90/180/270 y corregirla **antes** del OCR (aplicable a todos los motores, al
   inicio del pipeline).
4. DPI: si la imagen es pequeña (lado menor < ~1500 px), **upscalar ×2** con
   `cv2.INTER_CUBIC` antes de OCR. Verificar que los PDFs se rasterizan a
   **300 DPI** (revisar el parser PDF en `app/services/` o `app/parsers/`).
5. Llamar al preprocesado adecuado al inicio de cada `extract()`:
   - `tesseract.py` → `preprocess_for_tesseract`.
   - `paddle.py` y `pp_structure.py` → `preprocess_for_paddle`.
   - Trabajar siempre sobre una **copia temporal**; no machacar el original.
6. Manejo de errores: si el preprocesado falla, devolver la **ruta original**
   (como ya hace) pero **loguear a WARNING** el fallo con `logging.getLogger("app.ocr.preprocess")`.

**Aceptación**:
- [ ] Un escaneo inclinado 3° y con ruido produce más texto y mayor confianza
      media que sin preprocesar (test con imagen fixture).
- [ ] Una imagen rotada 90° recupera el texto correctamente (test OSD).
- [ ] PaddleOCR/PP-Structure **no** reciben imagen binarizada (test que verifica
      que `preprocess_for_paddle` no aplica `adaptiveThreshold`).
- [ ] Si el preprocesado lanza una excepción, el motor usa la ruta original y
      aparece un WARNING en logs (test inyectando fallo).
- [ ] Tests existentes en verde.

---

## FIX-3 · Score de calidad en la cascada, no longitud (O3) 🟠

**Archivos**: `app/ocr/cascading.py` (`_is_better`, `_is_acceptable`,
`_try_tier3`).

**Problema (verificado)**: `_is_better` decide por **número de caracteres**
("strictly more text"); `_try_tier3` solo acepta PP-Structure si produce *más
caracteres*. Un motor que mete ruido (más caracteres) gana al bueno → agrava
`low_ocr_confidence`.

**Cambio requerido**:

1. Introducir `_quality(result) -> float`:
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
2. `_is_better(cand, base)` → `_quality(cand) > _quality(base) + epsilon`
   (epsilon ≈ 0.01).
3. Tier 3 (PP-Structure) gana solo si su `_quality` supera al mejor previo, no
   por longitud.

**Aceptación**:
- [ ] Test unitario de `_quality`: texto con muchos símbolos pero largo NO
      supera a un texto limpio y corto de alta confianza.
- [ ] `_try_tier3` acepta PP-Structure por `_quality`, no por recuento de chars.
- [ ] Tests existentes en verde.

---

## FIX-4 · Logging y métricas de la cascada (O4) 🟠

**Archivos**: `app/ocr/cascading.py`, `app/services/metrics.py`.

**Problema (verificado)**: el `except Exception:` que captura el fallo de
Tier 2 y Tier 3 **no loguea nada** y devuelve el primario. Degradación
invisible — imposibilita diagnosticar `page_without_text` / `page_failed`.

**Cambio requerido**:

1. Añadir `logger = logging.getLogger("app.ocr.cascading")` y loguear a WARNING
   el motor que falló y la excepción en cada `except`.
2. Crear en `app/services/metrics.py` (o ampliar si existe):
   - `track_ocr_cascade_fallback(engine_name: str, reason: str) -> None`
   - Contador `ocr_tier_used_total{tier}` — registrar qué tier ganó por página
     (ya hay `self._name` en el motor; exponerlo como métrica).
3. Llamar a estas métricas desde `cascading.py`.

**Aceptación**:
- [ ] Al forzar excepción en el fallback de Tier 2/3, aparece un WARNING con el
      nombre del motor y el stacktrace.
- [ ] `track_ocr_cascade_fallback` y `ocr_tier_used_total` se incrementan
      correctamente (test con mock del motor que lanza).
- [ ] Tests existentes en verde.

---

## FIX-5 · Bug de regex `invoice_date_missing` (1 línea) 🟠

**Archivos**: `app/services/quality.py:89`, `app/services/dates.py`.

**Problema (verificado)**: `quality.py:89` comprueba si una factura tiene fecha
con `_DATE_PATTERN.search(clean_text)`, pero `DATE_PATTERN`
(`dates.py:44,87`) **solo admite fechas numéricas** (`DD/MM/YYYY` con `/` o `-`):

```python
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")
```

Ignora **fechas textuales en español**, patrón habitual de proveedores:
`"15 de junio de 2026"`, `"12 enero 2025"`. → la factura tiene fecha real pero
se marca `invoice_date_missing` (falso positivo). 32 docs afectados.

**Cambio requerido**:

1. En `quality.py`, sustituir:
   ```python
   if not _DATE_PATTERN.search(clean_text):
       flags.add("invoice_date_missing")
   ```
   por la función existente `find_dates_in_text(clean_text)` de `dates.py`, que
   **ya soporta** fechas numéricas Y textuales en español (meses con/sin
   acento, abreviaturas). Si la lista devuelta es vacía → flag.
2. Importar `find_dates_in_text` desde `app.services.dates`.
3. No tocar `_DATE_PATTERN` ni `dates.py` (ya están bien; el helper existe).

**Aceptación**:
- [ ] Test: un texto con `"Fecha: 15 de junio de 2026"` **no** activa
      `invoice_date_missing`.
- [ ] Test: un texto sin ninguna fecha (numérica ni textual) sí la activa.
- [ ] Tests existentes en verde.

---

## FIX-6 · Re-OCR + re-embed de documentos de baja confianza (A7) 🟡

**Archivos**: nuevo job en `app/workers/` o `app/services/maintenance.py`,
`app/ai/agent.py` (system prompt).

**Problema**: tras FIX-2, los documentos ya procesados con OCR malo siguen en
`needs_review` con `low_ocr_confidence` / `page_without_text` /
`text_too_short`. Hace falta reprocesarlos para que se beneficien del nuevo
preprocesado.

**Cambio requerido**:

1. Job de mantenimiento que seleccione documentos con:
   ```sql
   SELECT id FROM documents
   WHERE quality_flags_json::jsonb ?| ARRAY[
     'low_ocr_confidence','partial_low_ocr_confidence',
     'page_without_text','text_too_short'
   ];
   ```
   y los reencole para re-OCR + re-embed (mismo flujo que el procesamiento
   inicial, marcando `needs_reembedding`).
2. Ejecutarlo **después** de desplegar FIX-2/FIX-3, en lotes pequeños (para no
   saturar las GPUs) y con trazabilidad (job id, documento, antes/después).
3. En `app/ai/agent.py`: marcar chunks de fuente OCR dudosa (`confidence <
   0.70`) con `[OCR DUDOSO]` y añadir al system prompt: *"si la fuente está
   marcada como OCR dudoso, adviértelo en la respuesta"*.

**Aceptación**:
- [ ] Tras ejecutar el job, comparar `quality_score` y flags antes/después de
      una muestra (≥10 docs): la mayoría mejora score y pierde
      `low_ocr_confidence`.
- [ ] Una respuesta de IA basada en página de baja confianza incluye la
      advertencia de OCR dudoso (test).

---

## Orden de ejecución sugerido

| # | Tarea | Impacto | Esfuerzo |
|---|-------|---------|----------|
| 1 | FIX-1 — Migración `plans.project_phase` | Desbloquea 45 fallos | Bajo |
| 2 | FIX-2 — Preprocesado OCR por motor | Reduce ~675 docs en revisión | Medio |
| 3 | FIX-3 — Score de calidad en cascada | Reduce falsos "ganadores" | Bajo |
| 4 | FIX-4 — Logging/métricas cascada | Observabilidad | Bajo |
| 5 | FIX-5 — Bug regex `invoice_date_missing` | 32 falsos positivos | Trivial |
| 6 | FIX-6 — Re-OCR docs de baja confianza | Aplica FIX-2/3 al histórico | Medio |

**Dependencias**: FIX-6 depende de FIX-2 y FIX-3. El resto son independientes.
FIX-1, FIX-3, FIX-4, FIX-5 pueden ir en paralelo.

## NO abordar en esta tanda

Estos flags **no** se atacan directamente ahora (se reducen en cascada al
arreglar el OCR):

- `budget_number_missing`, `order_number_missing`, `supplier_missing`,
  `business_extraction_needs_review`: son **síntomas** de OCR malo o de regex
  estrechos. Tras FIX-2, reevaluar los que queden **con muestras reales** antes
  de tocar los patrones de `business_extraction.py` (ampliar regex a ciegas
  puede introducir falsos negativos).
- `document_type_unknown`: la mayoría son OCR insuficiente para clasificar.
  FIX-2 lo reduce.
- `security:invalid_*_signature` (9 docs): no es de OCR. Revisión manual caso
  a caso (archivo corrupto / renombrado / falso positivo del validador).

## Checklist de aceptación global

- [ ] Migración `plans` aplicada y verificada con `\d plans`.
- [ ] 45 jobs reencolados ya no fallan por `project_phase`.
- [ ] `preprocess_for_tesseract` / `preprocess_for_paddle` se llaman en cada
      `extract()` y son específicos (binarización solo para Tesseract).
- [ ] Deskew + OSD + DPI implementados y testeados con fixtures.
- [ ] La cascada decide por `_quality`, no por longitud (FIX-3).
- [ ] Los fallos de Tier 2/3 se loguean a WARNING y se miden (FIX-4).
- [ ] `invoice_date_missing` respeta fechas textuales en español (FIX-5).
- [ ] Job de re-OCR reduce `low_ocr_confidence` en el histórico (FIX-6).
- [ ] Tests existentes en verde + tests nuevos por tarea.
