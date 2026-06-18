# CTX-1 — Mapa del flujo de chat y retrieval

Documento de inventario generado ANTES de tocar código. Sirve como
contrato de lo que se va a modificar y por qué. Forma parte de la rama
`fix-grounded-chat-context-budget-scope`.

## Petición del usuario (resumen)

El asistente IA responde demasiado "básico": pierde el contexto
conversacional entre turnos, mezcla presupuestos distintos (260009 con
260011) en una misma búsqueda, y muestra fallbacks tipo
`"Tipo: desconocido | Estado: duplicate | Confianza: None | Paginas: None"`
que no son útiles para un usuario administrativo.

El objetivo de la rama es arreglar el flujo completo:

1. Mantener **estado conversacional activo** por sesión.
2. **Resolver referencias** como "este presupuesto" con ese estado.
3. Aplicar un **scope guard** por presupuesto activo (no contamina con
   otros presupuestos).
4. **Router de intención** previo al RAG.
5. **Datos estructurados (SQL) primero** y RAG como apoyo.
6. **Fallback grounded** en lenguaje de negocio, no metadatos crudos.
7. **Confidence gates** que bloquean afirmaciones de importes con OCR
   bajo / doc duplicado / doc sin clasificar.
8. **Formato de respuesta** estandarizado (directa + evidencia +
   fuentes + advertencias).
9. **Tests** que cubran los casos pedidos.
10. **Documentación** del nuevo comportamiento.

## Archivos existentes relevantes

| Archivo | Para qué lo vamos a tocar |
|---|---|
| `docu-intel/backend/app/ai/agent.py` | Orquestador. Inyectar estado activo, scope guard, intent router, formato estándar. Mantener 100% la API pública (re-exports). |
| `docu-intel/backend/app/ai/context.py` | `build_grounded_response` y `collect_context` con scope guard y fallback de negocio. |
| `docu-intel/backend/app/ai/tools.py` | `select_tools_for_question` para reconocer nuevos intents y emitir las tools estructuradas. |
| `docu-intel/backend/app/ai/validation.py` | `build_memory_block` → leer también el estado activo (no solo el historial). `response_fabricates_documents` endurecido para amounts candidatos. |
| `docu-intel/backend/app/ai/prompts.py` | System prompt con instrucciones para advertir de OCR bajo y no inventar. |
| `docu-intel/backend/app/tools/internal.py` | Implementar las nuevas tools SQL-first (`get_budget_total`, `get_budget_lines`, `get_invoiced_amount_for_budget`, `find_delivery_note_in_scope`, `find_shipping_cost_in_scope`, `get_invoice_origin_order`, `list_accepted_budgets_recent`). |
| `docu-intel/backend/app/api/routes/ai.py` | Aceptar `session_id` en `AskRequest` y propagarlo al orquestador. |
| `docu-intel/backend/app/schemas/ai.py` | Añadir `session_id: str | None` a `AskRequest`. |
| `docu-intel/backend/app/models/__init__.py` | Exportar los nuevos modelos `ChatSession` y `ChatMessage`. |
| `docu-intel/backend/app/services/ai_cache.py` | Incluir `session_id` en la clave de cache para no contaminar sesiones distintas. |

## Archivos nuevos

| Archivo | Propósito |
|---|---|
| `docu-intel/backend/app/models/chat_session.py` | Tablas `chat_sessions` y `chat_messages`. |
| `docu-intel/backend/alembic/versions/0035_chat_sessions.py` | Migración. |
| `docu-intel/backend/app/ai/active_context.py` | `ActiveContext` dataclass, `load_session`, `save_session`, `update_state` con keys: `current_budget_number`, `current_budget_id`, `current_client_name`, `current_folder_path`, `current_document_id`, `current_document_path`, `current_document_type`, `current_invoice_number`, `current_order_number`, `current_delivery_note_number`, `last_user_intent`, `last_retrieved_document_ids`. |
| `docu-intel/backend/app/ai/reference_resolver.py` | `resolve_references(question, state) -> resolved_question` (deícticos tipo "este presupuesto"). |
| `docu-intel/backend/app/ai/scope_guard.py` | `enforce_budget_scope(state, tools, filters) -> (tools, filters, warnings)`. `detect_global_intent(question) -> bool`. |
| `docu-intel/backend/app/ai/intent_router.py` | `classify_intent(question, state) -> Intent` con la lista de intents del enunciado. |
| `docu-intel/backend/app/ai/confidence_gates.py` | `evaluate_confidence_gates(context_items) -> dict[gate_name, reason]`. |
| `docu-intel/backend/app/ai/answer_format.py` | `format_grounded_answer(direct, evidence, sources, warnings, missing) -> str`. |
| `docu-intel/backend/tests/test_conversational_grounding.py` | 9 casos del enunciado. |
| `docu-intel/docs/CHAT_GROUNDED_BEHAVIOR.md` | Documentación de comportamiento. |

## Lo que NO se toca

- OCR / Tesseract / PaddleOCR / preprocesado (rama `upgrade-paddleocr-3-7-ppocrv6-structurev3-future-proof`).
- Auditoría / hardening / rate limiting / multi-tenant estricto (rama `codex/audit-remediation`).
- Tests de estabilización (rama `codex/stabilize-backend-tests`).
- Docker OCR / Dockerfiles.
- Modelos nuevos / migraciones destructivas.

## Riesgos

- Re-exports en `agent.py` deben permanecer para no romper la API
  pública. Tests existentes (`test_ai_agent_refactor`,
  `test_ai_ocr_confidence_prompt`, `test_ai_token_budget`,
  `test_ai_language_detection`, `test_tools_multilang`) importan
  nombres concretos de ahí.
- La nueva SQL-first path solo debe responder cuando hay datos
  estructurados; si no, degradar a RAG sin cambiar la respuesta
  existente.
- `session_id` en `AskRequest` debe ser opcional (None = sin sesión,
  comportamiento idéntico al actual) para no romper integraciones
  existentes.
