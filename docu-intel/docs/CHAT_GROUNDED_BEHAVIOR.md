# Comportamiento del chat IA grounded (CTX-1 .. CTX-10)

Este documento describe cómo se comporta el asistente IA de Docu-Intel
a partir de la rama `fix-grounded-chat-context-budget-scope`. Es la
referencia para operadores, integradores y para el equipo de QA.

## 1. Resumen ejecutivo

El asistente ahora:

1. **Recuerda el contexto activo de la conversación** (presupuesto,
   cliente, carpeta, documento, último intent) entre turnos dentro
   de la misma sesión.
2. **Resuelve referencias deícticas** (``"este presupuesto"``,
   ``"el albarán"``, ``"este pedido"``…) contra el contexto activo
   para que el LLM y el retrieval no se vayan a otro lado.
3. **Aísla la búsqueda por presupuesto activo** (scope guard) y
   respeta la voluntad explícita del usuario de buscar en todos los
   documentos.
4. **Clasifica la intención de la pregunta** (router heurístico) y
   encamina a una ruta SQL-first cuando existe dato estructurado
   (presupuestos, pedidos, facturas, albaranes, costes de envío).
5. **No inventa importes** con OCR bajo, documento duplicado, tipo
   desconocido o sin texto. Cuando un gate de confianza se abre, el
   sistema muestra los importes candidatos que el OCR pudo leer y
   dice al usuario que no puede confirmarlo.
6. **Devuelve un formato de respuesta uniforme** (respuesta directa
   / evidencia / documentos usados / advertencias / qué falta).
7. **Sustituye el fallback técnico** ("Tipo: desconocido | Estado:
   duplicate | Confianza: None | Paginas: None") por un mensaje en
   lenguaje de negocio: "Este documento está marcado como
   duplicado. No tiene una extracción de OCR propia. Su contenido
   útil está en el documento original del que procede."

## 2. Contexto conversacional activo

### 2.1 Qué se guarda

Cada sesión persiste un JSON (`chat_sessions.state_json`) con los
siguientes campos (ver `app/ai/active_context.py::ActiveContext`):

| Campo | Tipo | Significado |
|---|---|---|
| `current_budget_number` | `str` | Número del presupuesto activo (ej. ``"260009"``). |
| `current_budget_id` | `int` | PK del presupuesto activo (si la fila existe). |
| `current_client_name` | `str` | Cliente asociado al último documento resuelto. |
| `current_folder_path` | `str` | Carpeta del último documento resuelto. |
| `current_document_id` | `int` | PK del último documento resuelto. |
| `current_document_path` | `str` | Ruta completa del último documento resuelto. |
| `current_document_type` | `str` | Tipo documental del último documento resuelto. |
| `current_invoice_number` | `str` | Número de factura activo. |
| `current_order_number` | `str` | Número de pedido activo. |
| `current_delivery_note_number` | `str` | Número de albarán activo. |
| `last_user_intent` | `str` | Última intención clasificada (ver §4). |
| `last_retrieved_document_ids` | `list[int]` | IDs de los últimos documentos citados. |

### 2.2 Cuándo se actualiza

Al final de cada turno, en `app/ai/active_context.py::persist_context_after_answer`.
El orquestador pasa la intención, el documento resuelto y los
documentos citados. El JSON se actualiza y se persiste como parte
de la misma transacción que escribe el `AIAnswer` correspondiente.

### 2.3 Cómo se carga

`app/ai/active_context.py::load_active_context` lee la fila y
rehidrata el `ActiveContext`. La clave primaria lógica es el par
``(user_id, session_uuid)`` que viene del cliente en el campo
``session_id`` del `AskRequest`.

### 2.4 Esquema SQL

* `chat_sessions` (`id`, `user_id`, `session_uuid`, `state_json`,
  `last_seen_at`, `created_at`, `updated_at`).
* `chat_messages` (`id`, `session_id`, `question_id` opcional, `role`,
  `content`, `intent`, `was_structured_hit`, `created_at`).

Migración Alembic: `0035_chat_sessions` (down_revision =
`0034_invoice_deterministic_fields`).

## 3. Resolvedor de referencias (CTX-3)

`app/ai/reference_resolver.py::resolve_references(question, state)`
detecta frases deícticas y reescribe la pregunta para que el LLM y
el tool selector la entiendan con el contexto inyectado. Patrones
cubiertos:

* ``este/el/ese presupuesto`` → ``[Contexto: presupuesto N] …``
* ``este/el pedido``, ``que pedido origino esta factura`` →
  ``[Contexto: pedido N, factura M] …``
* ``esta/la factura``, ``esta proforma`` → ``[Contexto: factura M] …``
* ``el albarán``, ``el envio``, ``dispones del albaran`` →
  ``[Contexto: albaran X, presupuesto N] …``
* ``este/el plano``, ``de que trata el plano`` → ``[Contexto: …] …``
* ``este/el documento``, ``esta carpeta`` → ``[Contexto: …] …``
* ``por cuanto esta presupuestado``, ``importe total del
  presupuesto``, ``cuanto se ha facturado de …`` → contextualizado
  por presupuesto.

Si el estado activo no tiene la entidad que la referencia apunta,
el resolvedor deja la pregunta intacta y devuelve
``referenced_entity="none"``.

## 4. Scope guard por presupuesto (CTX-4)

`app/ai/scope_guard.py::enforce_budget_scope(question, state,
tools)`:

1. Si la pregunta pide explícitamente una vista global
   (``"global"``, ``"todos"``, ``"compara"``, ``"otros
   presupuestos"``, ``"últimos presupuestos"``, ``"en general"``),
   el scope guard **no** añade filtros.
2. Si el contexto activo tiene un presupuesto y el usuario no
   pidió global:
   * ``hybrid_search`` recibe ``source_path_like='%Presupuesto N%'``
     (y/o ``budget_scope_id`` cuando hay fila en
     `budget_scopes`).
   * ``get_budget_by_number`` se pre-rellena con el número activo si
     la pregunta no nombra uno.
   * ``aggregate_business`` se queda neutralizado cuando el usuario
     pregunta "por cuanto está presupuestado" y solo el presupuesto
     activo encaja.
3. Si no hay resultados en el scope, el orquestador inyecta la
   advertencia *"No he encontrado X dentro del presupuesto
   260009. Puedo buscar en todos los documentos si quieres."*

## 5. Intent router (CTX-5)

`app/ai/intent_router.py::classify_intent` clasifica la pregunta en
uno de los 15 intents. Lista completa:

| Intent | Frases típicas |
|---|---|
| `accepted_budgets` | ``últimos presupuestos aceptados``, ``presupuestos aceptados sin pedido`` |
| `budget_summary` | ``de que trata el presupuesto X`` |
| `budget_total` | ``por cuanto esta presupuestado``, ``importe total del presupuesto`` |
| `budget_lines` | ``que lineas tiene este presupuesto``, ``desglose del presupuesto`` |
| `budget_status` | ``esta aceptado el presupuesto X?`` |
| `invoiced_amount_for_budget` | ``cuanto se ha facturado de …``, ``importe facturado`` |
| `invoice_origin_order` | ``que pedido origino esta factura`` |
| `delivery_note_lookup` | ``dispones del albaran``, ``hay albaran de entrega`` |
| `shipping_cost_lookup` | ``cuanto costo el envio``, ``portes``, ``flete`` |
| `supplier_breakdown` | ``desglosado por proveedor``, ``por proveedor`` |
| `time_filtered_query` | ``este año``, ``en 2024``, ``este mes`` |
| `plan_summary` | ``de que trata el plano X`` |
| `document_summary` | ``de que trata el documento X`` |
| `related_documents` | ``documentos relacionados``, ``que hay en la misma carpeta`` |
| `generic_document_question` | (fallback) |

Si la pregunta coincide con un intent de los que necesitan estado
(``budget_total``, ``delivery_note_lookup``, …) y la sesión no
tiene contexto suficiente, el router marca
``needs_state=True`` y el orquestador deja un log de aviso.

## 6. Datos estructurados antes que RAG (CTX-6)

`app/ai/tools.py::select_structured_tools` mira la clasificación
del router y emite la tool SQL-first adecuada:

| Intent | Tool SQL | Implementación |
|---|---|---|
| `budget_total` | `get_budget_total` | Suma `total_amount` de `Budget` y valida contra `BudgetLine.total_price`. |
| `budget_lines` | `get_budget_lines` | Devuelve hasta 25 `BudgetLine` con referencia, descripción, cantidad, precio. |
| `invoiced_amount_for_budget` | `get_invoiced_amount_for_budget` | `Budget → related Orders → related Invoices → total`. |
| `accepted_budgets` | `list_recent_accepted_budgets` | `Budget.accepted_detected=true` ordenados por `created_at desc`. |
| `invoice_origin_order` | `get_invoice_origin_order` | `Invoice.related_order_id` y luego el `related_budget_id` del pedido. |
| `delivery_note_lookup` | `find_delivery_note_in_scope` | `Document.document_type=albaran` filtrado por `source_path_like` del scope. |
| `shipping_cost_lookup` | `find_shipping_cost_in_scope` | `DocumentChunk.chunk_text ILIKE %envio|portes|flete|…%` dentro del scope. |

Si la tool estructurada devuelve ``found=False``, el orquestador
sigue con la cascada de tools habitual (`hybrid_search`, etc.) y
añade una advertencia explicando que no se encontró en datos
estructurados.

## 7. Confidence gates y anti-invención (CTX-8)

`app/ai/confidence_gates.py::evaluate_confidence_gates` evalúa cinco
gates sobre la pregunta + contexto + documento resuelto:

| Gate | Disparador | Efecto |
|---|---|---|
| `ocr_baja_confianza` | `ocr_confidence < 0.70` o `confidence < 0.70`. | Bloquea importe + warning al LLM. |
| `documento_duplicado` | `Document.status == "duplicate"`. | Bloquea importe + warning. |
| `tipo_documento_desconocido` | `Document.document_type` ∈ {`"desconocido"`, `"unknown"`}. | Bloquea importe + warning. |
| `necesita_revision` | `Document.status == "needs_review"`. | Bloquea importe + warning. |
| `sin_texto_ocr` | Excerpt + summary del top item están vacíos. | Bloquea importe + warning. |
| `texto_muy_corto` | Texto < 40 chars o < 50% alfanumérico. | Bloquea importe + warning. |

Los gates sólo **bloquean** (skipean el LLM y emiten la respuesta
segura de §9) cuando la pregunta **exige un importe**
(``budget_total``, ``invoiced_amount_for_budget``,
``shipping_cost_lookup``). En el resto de intents los gates son
informativos y se inyectan en el prompt del LLM como una línea
``Aviso: …``.

## 8. Fallback grounded (CTX-7)

`app/ai/context.py::build_grounded_response` detecta si el top
context item es un documento resuelto y, según su estado, produce
una respuesta en lenguaje de negocio en vez de volcar metadatos:

| Estado del documento | Mensaje |
|---|---|
| `status == "duplicate"` | "Este documento está marcado como **duplicado**… Su contenido útil está en el documento original del que procede. En la misma carpeta hay: **X**, **Y**. Recomiendo abrir el original." |
| `document_type` ∈ {`"desconocido"`, `"unknown"`} | "Todavía no he clasificado este documento (sigue marcado como tipo \"desconocido\"). Recomiendo re-procesarlo desde la ficha del documento." |
| OCR < 70% | "La lectura OCR es de baja calidad (55% de confianza). No puedo confirmar el contenido. Recomiendo re-procesar este PDF con el motor OCR avanzado (PaddleOCR v3 / PP-Structure)." |
| Sin texto OCR | "He encontrado el documento pero no tiene texto OCR extraido. Recomiendo re-procesar este archivo desde su ficha." |
| OK | (fallback quote-based tradicional con cita del fragmento). |

## 9. Formato estándar de respuesta (CTX-9)

Cuando un confidence gate bloquea al LLM, la respuesta sigue el
formato de cinco secciones definido en
`app/ai/answer_format.py::format_grounded_answer`:

1. **Respuesta directa** (una línea).
2. **Evidencia** (lista de hechos, incluyendo importes candidatos
   cuando aplique).
3. **Documentos usados** (citas de los `Document` con número de
   página).
4. **Advertencias de confianza** (gates abiertos, warnings del
   scope guard, del intent router, etc.).
5. **Qué falta** (lo que el usuario podría haber preguntado y no
   se encontró).

### Ejemplo antes / después

Antes (master):

> Usuario: ``de que trata el plano VISTA ALEGRE carpinteria.pdf``
> Respuesta: *"Tipo: desconocido | Estado: duplicate |
> Confianza: None | Paginas: None"*

Después (CTX-7 + CTX-9):

> *"Este documento está marcado como **duplicado** dentro del
> sistema, así que no tiene una extracción de OCR propia. Su
> contenido útil está en el documento original del que procede. En
> la misma carpeta hay otros documentos que pueden ser el
> original: **VISTA ALEGRE planta.pdf**. Recomiendo abrir el
> original en lugar de este PDF."*

Antes:

> Usuario (con presupuesto 260009 activo): ``por cuanto esta
> presupuestado``
> Respuesta: *"la suma total de importes de presupuestos mencionada
> es 8900.8 (48 documentos)"* (mezclando 260011, 260039…).

Después:

> *"No puedo confirmarlo con seguridad para el presupuesto
> 260009 porque el documento tiene una o varias señales de baja
> calidad: ocr_baja_confianza. No he fabricado un importe a partir
> de una lectura dudosa.*
>
> **Evidencia:**
> * **1.234,56 EUR** en `pres_260009.pdf` (pag. 1) — confianza
>   55%
>
> **Documentos usados:**
> * `pres_260009.pdf`
>
> **Advertencias:**
> * Hay fuentes marcadas como OCR dudoso…
>
> **Qué falta:**
> * No he encontrado un total claro."*

## 10. Cómo probarlo manualmente

### 10.1 Sin servidor (sesión stateless)

```bash
curl -X POST http://localhost:8000/api/v1/ai/ask \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"question": "ultimos presupuestos aceptados"}'
```

Debe responder con la lista de presupuestos aceptados (sin
importes si el usuario no tiene permiso de precios).

### 10.2 Con sesión (recomendado)

```bash
SID=$(uuidgen)
curl -X POST http://localhost:8000/api/v1/ai/ask \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"de que trata el presupuesto 260009\", \"session_id\": \"$SID\"}"

curl -X POST http://localhost:8000/api/v1/ai/ask \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"por cuanto esta presupuestado\", \"session_id\": \"$SID\"}"
```

La segunda pregunta debe resolverse dentro del presupuesto 260009
(sin contaminarse con 260011 o 260039).

### 10.3 Override explícito de scope

```bash
curl -X POST http://localhost:8000/api/v1/ai/ask \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"busca en todos los presupuestos\", \"session_id\": \"$SID\"}"
```

Debe advertir *"El usuario ha pedido una vista global; se ignorará
el ámbito del presupuesto activo"* y dar resultados agregados.

## 11. Tests

`docu-intel/backend/tests/test_conversational_grounding.py` cubre
los nueve casos del enunciado más un puñado de tests unitarios por
módulo:

* ActiveContext round-trip + `scope_filters()`.
* `resolve_references` para presupuesto, factura, albarán y
  referencias sin estado.
* Scope guard: pinning, override de `get_budget_by_number`,
  no-overrides de presupuesto explícito, "todos" libera el scope.
* Intent router: cada intent, `needs_state` cuando falta contexto.
* Structured tools: `get_budget_total`, `get_invoiced_amount`,
  `find_delivery_note_in_scope` filtrado por `source_path_like`.
* Friendly fallback: duplicate, unknown, OCR bajo.
* Confidence gates: bloqueo de importe, no-bloqueo para preguntas
  no-importe, extracción de candidatos, gate de duplicado.
* Formato estándar: cinco secciones, mención del scope cuando no
  hay resultados.

Para ejecutarlos:

```bash
cd docu-intel/backend
python -m pytest tests/test_conversational_grounding.py -v
```

## 12. Limitaciones conocidas

* El follow-up entre sesiones distintas **no se propaga**: cada
  `session_id` tiene su propio `ActiveContext`. Para auditoría se
  puede consultar la tabla `chat_sessions`.
* La inferencia de "el albarán" asume que el estado activo contiene
  la ruta de la carpeta (``current_folder_path``). Si el usuario
  solo dijo "el albarán" sin haber resuelto previamente un
  documento, el resolvedor devuelve noop y el orquestador pide
  aclaración.
* El gate `ocr_baja_confianza` usa el umbral de 70% que ya estaba
  hardcodeado en el sistema (constante
  `LOW_OCR_CONFIDENCE_THRESHOLD`). Cambiarlo en
  `app/ai/context.py` lo propaga a todos los gates.
* La búsqueda SQL-first funciona con un set limitado de preguntas
  (ver §6). Cualquier otro intent cae a la cascada de tools
  habitual (`hybrid_search`, etc.).
* La lista de `SHIPPING_KEYWORDS` está cerrada. Para añadir
  sinónimos (p. ej. "transitario") editar la constante en
  `app/tools/internal.py`.
