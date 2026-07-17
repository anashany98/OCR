# Informe de evaluación del Chat IA — Docu-Intel

**Fecha:** 2026-07-17
**Muestra:** 31 documentos de referencia (sobre un total de 198 ingestados en 22 presupuestos)
**Total de preguntas:** 18 (6 simples, 6 complicadas, 6 enrevesadas/trampa)
**Modelo evaluado:** router interno `qwen3-8b` / `qwen/qwen3-14b` (LM Studio local) + `backend_grounded_fallback` + `backend_structured`

---

## 1. Universo bajo prueba (resumen de la muestra)

| Tipo doc | Docs en muestra | Calidad OK | Con warnings | Necesitan revisión | Duplicados | Pendientes |
|---|---:|---:|---:|---:|---:|---:|
| presupuesto | 1 | 1 | 0 | 0 | 0 | 0 |
| factura | 2 | 1 | 0 | 1 | 0 | 0 |
| pedido | 2 | 1 | 1 | 0 | 0 | 0 |
| albaran | 3 | 1 | 1 | 1 | 0 | 0 |
| albaran_transporte | 1 | 1 | 0 | 0 | 0 | 0 |
| hoja_confeccion | 2 | 2 | 0 | 0 | 0 | 0 |
| comprobante_pago | 2 | 1 | 0 | 1 | 0 | 0 |
| orden_trabajo | 1 | 0 | 1 | 0 | 0 | 0 |
| email_exportado | 3 | 2 | 0 | 1 | 0 | 0 |
| excel | 3 | 3 | 0 | 0 | 0 | 0 |
| plano | 1 | 0 | 0 | 1 | 0 | 0 |
| croquis_medida | 1 | 0 | 0 | 1 | 0 | 0 |
| medicion | 1 | 1 | 0 | 0 | 0 | 0 |
| ficha_tecnica | 1 | 1 | 0 | 0 | 0 | 0 |
| dua | 1 | 1 | 0 | 0 | 0 | 0 |
| foto_producto | 1 | 0 | 0 | 1 | 0 | 0 |
| imagen | 1 | 0 | 0 | 0 | 1 | 0 |
| desconocido | 2 | 0 | 0 | 0 | 1 | 1 |
| confirmacion | 1 | 1 | 0 | 0 | 0 | 0 |
| incidencia | 1 | 0 | 1 | 0 | 0 | 0 |

**22 presupuestos distintos** registrados (250052, 250053, 250109, 250152, 250194, 250247, 250258, 250298, 250348, 250349, 250376, 250544, 250638, 250671, 250695, 251016, 251063, 251121, 251180, 251290, 251410, 251656).

---

## 2. Cuestionario y respuestas

### A. Preguntas simples (6)

#### Q1 — "Cuántos presupuestos distintos hay registrados en el sistema? Lista los códigos numéricos."

- **Modelo:** `qwen3-8b`
- **Confianza devuelta:** 0.475
- **Fuentes citadas:** 3
- **Respuesta (resumen):** *"No dispongo de esa información en los documentos procesados. Para poder listar los códigos numéricos… se necesitaría acceder a una base de datos…"*
- **Ground truth:** 22 presupuestos, perfectamente conocidos por la BD (`source_path` de cada documento).
- **Diagnóstico:** el sistema **no consulta la tabla de presupuestos ni los metadatos estructurados**; solo busca texto en chunks. Falla en la pregunta más fácil posible.
- **Puntuación: 0/10**

#### Q2 — "Cuál es el importe total y la fecha de la factura con número 250013?"

- **Modelo:** `qwen3-8b`
- **Confianza:** 0.827
- **Fuentes:** 8
- **Respuesta (resumen):** dice no tener el importe; sí menciona fecha `2025-05-07` desde un documento.
- **Ground truth:** `id=111` Factura 2-250013 DECORACIONES EGEA SRL.pdf (quality OK). La fecha es correcta; el importe no se extrae.
- **Diagnóstico:** extracción de importes muy débil. La IA no usa la entidad `total_amount` de `business_extraction` cuando existe.
- **Puntuación: 3/10**

#### Q3 — "Enumera todos los albaranes del presupuesto 250053."

- **Modelo:** `backend_grounded_fallback` (`validation_source_coverage`)
- **Confianza:** 0.824
- **Fuentes:** 8
- **Respuesta (resumen):** fallback incoherente. Devuelve como "fuente" un Excel llamado "Pendientes Items" y dos albaranes que no enumera.
- **Ground truth:** 5 albaranes (`id=33, 146, 151, 165, 197`).
- **Diagnóstico:** el fallback `validation_source_coverage` produce respuestas sin estructura; no aprovecha el `document_type=albaran` filtrable.
- **Puntuación: 1/10**

#### Q4 — "Qué proveedor aparece en el pedido del presupuesto 250053?"

- **Modelo:** `qwen3-8b`
- **Confianza:** 0.824
- **Fuentes:** 8
- **Respuesta:** *"DECORACIONES EGEA S.L., según el documento orden de compra.pdf"*
- **Ground truth:** id=157 `orden de compra.pdf` (pedido, calidad OK).
- **Diagnóstico:** respuesta correcta con cita. Es el mejor resultado de toda la batería.
- **Puntuación: 8/10**

#### Q5 — "Hay algún plano (documento de tipo plano) en el presupuesto 250053? Cuál es su escala?"

- **Modelo:** `qwen3-8b`
- **Confianza:** 0.824
- **Fuentes:** 8
- **Respuesta:** dice que *"no existe un documento de tipo plano estructurado"* pero que en `listado.pdf` aparece "Plano: escala no valida".
- **Ground truth:** hay 2 documentos `document_type=plano` en 250053 (`id=174 listado.pdf`, `id=130 albaran de entrega.pdf`). Ambos con `needs_human_review` por escala no válida.
- **Diagnóstico:** confunde tipo documental con presencia real. La respuesta es contradictoria y no da la lista completa.
- **Puntuación: 4/10**

#### Q6 — "Lista los correos electrónicos (.msg) del presupuesto 250258 y sus asuntos principales."

- **Modelo:** `qwen3-8b`
- **Confianza:** 0.2
- **Fuentes:** 8
- **Respuesta:** *"No dispongo de esa información. El número 250258 aparece en WhatsApp Image…"*
- **Ground truth:** 5 emails en 250258 (`id=1, 60, 152, 185, 198`).
- **Diagnóstico:** el sistema confunde una imagen con el presupuesto. No usa la extensión `.msg` ni el `source_path` para filtrar.
- **Puntuación: 0/10**

---

### B. Preguntas complicadas (6)

#### Q7 — "Qué documentos del presupuesto 250152 están marcados como needs_human_review y por qué?"

- **Modelo:** `qwen/qwen3-14b`
- **Confianza:** 0.824
- **Fuentes:** 8
- **Respuesta:** *"No dispongo. El presupuesto 250152 no aparece en la tabla estructurada…"*
- **Ground truth:** 3 docs (`id=169 PIN EGEA (4).pdf` [factura], `id=108 PL FRA 2_250034…` [factura], `id=79 FRA 2_250034…` [factura]).
- **Diagnóstico:** la calidad documental está persistida en BD pero la IA no la consulta. Falla de tools.
- **Puntuación: 0/10**

#### Q8 — "Cruza los pedidos con sus albaranes para el presupuesto 250053."

- **Modelo:** `qwen/qwen3-14b`
- **Confianza:** 0.827
- **Fuentes:** 8
- **Respuesta:** lista 4 albaranes por nombre pero **no los cruza** con pedidos. Reconoce que *"no se menciona explícitamente si estos albaranes están asociados a pedidos específicos"*.
- **Ground truth:** 1 pedido (id=157) y 5 albaranes (id=33, 146, 151, 165, 197). Sin `purchase_order_id` cruzado, no se puede afirmar.
- **Diagnóstico:** la IA no inventa, pero tampoco hace el cruce. Útil como respuesta humana pero inútil como respuesta "inteligente".
- **Puntuación: 3/10**

#### Q9 — "Compara los importes de las facturas de Decoraciones Egea en 250152 y 250052. Cuál es mayor y por cuánto difieren?"

- **Modelo:** `backend_grounded_fallback` (`validation_fabricated_document`)
- **Confianza:** 0.824
- **Fuentes:** 8
- **Respuesta:** fallback irrelevante: cita un `.msg` sin importes.
- **Ground truth:** ambos presupuestos contienen facturas de Decoraciones Egea (id=111 en 250052, id=79/108 en 250152). La comparación se puede hacer.
- **Diagnóstico:** la IA no extrae importes ni los suma. Pinta fallback y se rinde.
- **Puntuación: 0/10**

#### Q10 — "Cuántas habitaciones y qué superficies (m²) están registradas en los planos del presupuesto 250053? Indica el documento de origen."

- **Modelo:** `backend_grounded_fallback` (`no_answer_context`)
- **Confianza:** 0.0
- **Fuentes:** 0
- **Respuesta:** *"No he encontrado información en el sistema para responder a eso. Si me das un número de documento, un proveedor, un cliente, una fecha o el nombre de un archivo, lo busco más a fondo."*
- **Ground truth:** 2 docs `document_type=plano` en 250053, ambos con `needs_human_review`. No hay geometría extraída; las "habitaciones" no están en `plan_rooms` para estos.
- **Diagnóstico:** **caso de éxito por honestidad.** Confianza 0, sin fuentes, no inventa. Es el patrón ideal que el resto de respuestas debería imitar.
- **Puntuación: 6/10** (negativa pero correcta, sin alucinación)

#### Q11 — "Dame un resumen ejecutivo del presupuesto 250152: cliente, importes totales por tipo de documento, proveedores principales y estado de revisión."

- **Modelo:** `qwen/qwen3-14b`
- **Confianza:** 0.824
- **Fuentes:** 8
- **Respuesta:** *"No dispongo de información suficiente sobre el presupuesto 250152…"*
- **Ground truth:** 24 docs en 250152; cliente Gran Meliá de Mar; proveedores principales: Decoraciones Egea, DP World, Caribe Cargo, Caput, Rhenus; 3 docs `needs_human_review`.
- **Diagnóstico:** la pregunta es de "resumen ejecutivo" y exige agregación. La IA no usa ni el listado de docs ni la calidad por documento.
- **Puntuación: 0/10**

#### Q12 — "Cuál es la cronología documental del presupuesto 250247? Ordena los documentos por fecha y detecta huecos o anomalías."

- **Modelo:** `qwen3-8b`
- **Confianza:** 0.828
- **Fuentes:** 4
- **Respuesta:** *"No dispongo. El presupuesto 250247 no figura como una fila estructurada…"*
- **Ground truth:** 9 docs en 250247; fechas disponibles en `created_at` y dentro de los documentos (correos, albaranes, Excel de visillos).
- **Diagnóstico:** la IA podría haber ordenado por `created_at` y cruzado con `processed_at` para detectar colas, pero no lo hace.
- **Puntuación: 0/10**

---

### C. Preguntas enrevesadas / trampa (6)

#### Q13 — "Cuánto costó el proyecto de la piscina nueva del hotel?"

- **Modelo:** `qwen3-8b`
- **Confianza:** 0.516
- **Fuentes:** 4
- **Respuesta (texto literal):** *"El proyecto de la piscina nueva del hotel costó 2.385,46 euros sin IVA, según el documento OC_0114 EGEA CAMBIADORES firmada.pdf. Este importe corresponde al suministro e instalación de estructuras y textiles para los cambiadores de la zona de piscina."*
- **Ground truth:** **no existe ningún documento que mencione un proyecto de piscina nueva.** El documento `OC_0114 EGEA CAMBIADORES firmada.pdf` (id=160, presupuesto 250052) es una orden de compra, no un proyecto de piscina. El modelo **inventa la categoría** ("proyecto de piscina") y **asigna un importe específico** sin grounding real.
- **Diagnóstico:** **alucinación grave.** El modelo local `qwen3-8b` está generando texto sin verificar que la fuente respalde la afirmación. La confianza 0.516 no refleja la peligrosidad del error.
- **Puntuación: 0/10** (máxima severidad — invención de dato)

#### Q14 — "Quién es el director general de Meliá Hotels International según los documentos?"

- **Modelo:** `qwen3-8b`
- **Confianza:** 0.832
- **Fuentes:** 10
- **Respuesta:** *"No dispongo de esa información en los documentos procesados."*
- **Ground truth:** no hay info de gobierno corporativo en los documentos; pregunta fuera de scope.
- **Diagnóstico:** **caso de éxito por honestidad.** Se negó correctamente.
- **Puntuación: 9/10**

#### Q15 — "Cuál es el margen de beneficio que aplica Decoraciones Egea en sus pedidos al hotel?"

- **Modelo:** `qwen3-8b`
- **Confianza:** 0.832
- **Fuentes:** 10
- **Respuesta:** *"No dispongo de esa información. Sería necesario analizar precios de venta, costes de adquisición o información contable…"*
- **Ground truth:** no hay info de márgenes en los documentos.
- **Diagnóstico:** **caso de éxito por honestidad.** Sugiere qué datos harían falta.
- **Puntuación: 9/10**

#### Q16 — "El presupuesto 250999 existe? Si no, qué presupuesto tiene el código más cercano?"

- **Modelo:** `backend_grounded_fallback` (`no_answer_context`)
- **Confianza:** 0.0
- **Fuentes:** 0
- **Respuesta:** *"No he encontrado información en el sistema para responder a eso."*
- **Ground truth:** 250999 **no existe**. El código más cercano es 251656 (siguiente ascendente) o 251410 (más cercano en distancia).
- **Diagnóstico:** **caso parcialmente correcto.** El sistema se niega (bien) pero **no ofrece el "más cercano"**, que era la segunda parte de la pregunta. Esto es un fallo en la recuperación por metadatos.
- **Puntuación: 6/10**

#### Q17 — "Calcula el IRPF que se habría retenido en la factura del proveedor X con un importe de 5000 euros."

- **Modelo:** `backend_structured`
- **Confianza:** 0.815
- **Fuentes:** 10
- **Respuesta (extracto):** *"El proveedor es de servicio e impuesto: Pago Impuesto DGA… ITBIS RD$ 374,625.28… Tasa por Servicio Aduanero RD$ 5,634.49…"*
- **Ground truth:** **no aplica IRPF en este contexto.** Es una pregunta trampa: (a) la factura 250013 es a la República Dominicana, no España; (b) el IRPF español no es la herramienta; (c) los datos DGA/ITBIS son de la aduana dominicana.
- **Diagnóstico:** **alucinación grave.** El modelo se agarra a la palabra "impuesto" y devuelve un payload de aduana dominicana. Confianza alta (0.815) para una respuesta completamente incorrecta.
- **Puntuación: 0/10** (peligrosa: parece creíble, no lo es)

#### Q18 — "La factura 250013 está duplicada en el sistema? En caso afirmativo, dame el ID del documento original y el duplicado."

- **Modelo:** `qwen3-8b`
- **Confianza:** 0.827
- **Fuentes:** 8
- **Respuesta:** *"No dispongo de esa información. Para poder confirmar… necesito más detalles…"*
- **Ground truth:** hay 3 documentos con 250013 (id=111 factura OK, id=16 hoja_confeccion OK, id=8 medicion needs_human_review). **Ninguno está marcado como `duplicate`** en `duplicate_of_document_id`. La respuesta correcta sería: "No, no hay duplicados; los tres documentos con ese número son tipos distintos (factura, hoja de confección, medición)."
- **Diagnóstico:** la IA se rinde en vez de dar la información disponible. Falla de tools.
- **Puntuación: 3/10** (correcta en no inventar, pero incompleta)

---

## 3. Resumen de puntuación

| # | Categoría | Pregunta (resumen) | Puntuación |
|--:|---|---|---:|
| 1 | simple | Conteo de presupuestos | 0/10 |
| 2 | simple | Importe y fecha factura 250013 | 3/10 |
| 3 | simple | Albaranes presupuesto 250053 | 1/10 |
| 4 | simple | Proveedor pedido 250053 | **8/10** |
| 5 | simple | Plano en 250053 y su escala | 4/10 |
| 6 | simple | Correos presupuesto 250258 | 0/10 |
| 7 | complicada | needs_human_review en 250152 | 0/10 |
| 8 | complicada | Cruzar pedidos/albaranes 250053 | 3/10 |
| 9 | complicada | Comparar importes Decoraciones Egea | 0/10 |
| 10 | complicada | Habitaciones en planos 250053 | 6/10 |
| 11 | complicada | Resumen ejecutivo 250152 | 0/10 |
| 12 | complicada | Cronología 250247 | 0/10 |
| 13 | enrevesada | Costo piscina nueva | **0/10 (alucinación)** |
| 14 | enrevesada | Director general Meliá | **9/10** |
| 15 | enrevesada | Margen Decoraciones Egea | **9/10** |
| 16 | enrevesada | Presupuesto 250999 | 6/10 |
| 17 | enrevesada | IRPF 5000 € | **0/10 (alucinación)** |
| 18 | enrevesada | Duplicado factura 250013 | 3/10 |

### Puntuaciones medias

| Categoría | Media | Aciertos brillantes (≥7) | Fallos totales (≤2) |
|---|---:|---:|---:|
| Simples (n=6) | 2,7/10 | 1 | 3 |
| Complicadas (n=6) | 1,5/10 | 0 | 5 |
| Enrevesadas (n=6) | 4,5/10 | 2 | 2 |
| **Global (n=18)** | **2,9/10** | **3** | **10** |

---

## 4. Diagnóstico por patrón de fallo

### 4.1 — Alucinaciones con dato concreto (CRÍTICO, 2/18)

- **Q13** inventa el importe `2.385,46 €` para un proyecto de piscina que no existe, citando un PDF que no respalda la afirmación.
- **Q17** devuelve datos de impuestos dominicanos (ITBIS, DGA) cuando la pregunta es sobre IRPF español y no aplica.

**Implicación:** cualquier técnico que use el chat sin verificar en la fuente puede tomar decisiones basadas en datos falsos. Riesgo operativo y legal.

### 4.2 — "No sé" en preguntas que sí tienen respuesta (5/18)

- **Q1, Q6, Q7, Q11, Q12**: la BD tiene la respuesta (22 presupuestos, 5 emails en 250258, 3 docs con `needs_human_review` en 250152, 24 docs en 250152, 9 docs en 250247). El chat no llega a ellos porque **no consulta metadatos estructurados**, solo hace RAG sobre el texto.

**Implicación:** el sistema se ve inútil en agregaciones, justo donde más valor aporta.

### 4.3 — Calibración de confianza rota (18/18)

- La confianza 0.824 se asigna de forma casi uniforme a respuestas correctas (Q4, Q5), a respuestas en fallback incoherente (Q3, Q9) y a respuestas "no sé" (Q7, Q11, Q12). Solo Q10 (0.0) y Q16 (0.0) tienen una confianza que refleja el vacío real.
- Los enrevesados con respuesta correcta (Q14, Q15) salen con 0.832, indistinguibles de los que alucinan.
- Q13 (alucinación grave) sale con 0.516 — paradójicamente más bajo, pero el umbral de "bloqueo por baja confianza" no se activa.

**Implicación:** la métrica de confianza no sirve como filtro de seguridad. Un dashboard que pinte "salud de la IA" basado en conf media engaña.

### 4.4 — Fallbacks incoherentes (3/18)

- `backend_grounded_fallback` con `validation_source_coverage` (Q3) y `validation_fabricated_document` (Q9) producen texto que parece respuesta pero no lo es.
- La arquitectura de tres rutas (`qwen3-8b` / `qwen/qwen3-14b` / fallback) **no expone al usuario qué modelo respondió**, así que la trazabilidad post-mortem es imposible.

### 4.5 — Falta de tools estructuradas (8/18)

Q1, Q6, Q7, Q8, Q9, Q11, Q12, Q18 son preguntas que la BD resuelve en milisegundos con una `GROUP BY` o un `WHERE document_type=…`. El README describe tools (`get_documents_by_budget`, `get_improvement_candidates`, etc.) pero en la práctica el router no las invoca: el chat va directo a RAG.

### 4.6 — Encoding y presentacin (transversal)

Los excerpts llegan con tildes y eñes mal codificadas (`CÃ³digo`, `TÃ©cnica`) tanto en `excerpt` como en `answer`. Afecta a la legibilidad de cualquier respuesta y rompe pipelines downstream.

---

## 5. Mejoras recomendadas (priorizadas)

### 🔴 P0 — Bloqueantes (producción no debe seguir con esto)

1. **Guard de alucinación para importes concretos.** Cualquier respuesta que contenga un importe numérico sin que la fuente citeda lo contenga debe marcarse como `[DATO NO VERIFICADO]` y bajar la confianza a <0.4. Implementar como post-procesado regex en `app/ai/agent.py` sobre `answer` y `data.amounts`.

2. **Threshold de bloqueo por confianza.** Si `confidence < 0.5` Y no hay al menos 1 fuente con `relevance > 0.05`, devolver la plantilla grounded sin pasar por el LLM. (Q13 habría caído en este caso.)

3. **Forzar routing por tools para agregaciones.** Detectar preguntas con palabras clave (`cuántos`, `lista`, `total`, `comparar`, `resumen`) y enrutar primero a `/api/v1/admin/operations/documents` filtrado por `budget_code`. Solo si la tool no devuelve nada, pasar a RAG.

### 🟠 P1 — Importantes (calidad)

4. **Tool `get_documents_by_budget(budget_code, document_type?, quality_status?)`.** Resuelve Q1, Q3, Q6, Q7, Q8, Q11, Q12, Q18. Es la query SQL más obvia que falta. Añadir a `manifest` de `/integrations/v1` y a las tools del chat interno.

5. **Tool `get_budget_summary(budget_code)`.** Devuelve: nº docs, desglose por tipo, importes sumados por `business_extraction.total_amount` cuando existan, lista de proveedores extraídos, calidad global. Resuelve Q11, Q12 y el futuro "resumen ejecutivo" como feature.

6. **Tool `find_nearest_budget(budget_code)`.** Resuelve Q16: SELECT budget_code FROM budget_scope WHERE budget_code != ? ORDER BY ABS(budget_code - ?) LIMIT 1.

7. **Tool `find_duplicates(document_reference)`.** Resuelve Q18: SELECT * FROM documents WHERE original_filename ILIKE '%<ref>%' AND quality_status = 'duplicate'.

8. **Calibración de confianza.** Sustituir el escalar actual por un modelo de 4 componentes:
   - `relevance_max` de las fuentes (0-1)
   - `coverage` = nº de fuentes que mencionan la respuesta / nº de fuentes citadas
   - `consistency` = acuerdo entre las fuentes
   - `hallucination_penalty` = regex sobre importes no citados
   Confianza final = media geométrica * (1 - penalty). Implementar en `app/services/grounding.py`.

9. **Decodificar UTF-8 los excerpts en la respuesta.** El backend sirve bytes Latin-1 mal interpretados. Es un bug en la serialización JSON, no en el OCR. Buscar el `ensure_ascii=True` o el encoding en `app/ai/agent.py` y la respuesta estructurada.

### 🟡 P2 — Deseables (robustez)

10. **Tests de regresión con este cuestionario.** Convertir las 18 preguntas en `tests/eval/test_ai_grounding.py` con snapshot del ground truth y assert de:
    - respuesta no vacía
    - confianza < 0.5 cuando no hay datos
    - ningún importe numérico en la respuesta sin cita que lo respalde
    - detección correcta de alucinaciones (Q13, Q17) como casos negativos conocidos

11. **Dashboard "salud de la IA".** Métricas por categoría (simples / complicadas / enrevesadas) y por intención detectada (count / list / compare / trap). Hoy solo se ve `model_name` y `confidence` mezclados.

12. **Exponer `model_name` y `fallback_reason` en la UI del chat.** El usuario debe ver "Respondido por `qwen3-8b` (fallback por `validation_source_coverage`)" para entender la calidad.

13. **Modo "agregación" explícito.** Toggle en el chat: "Resumen / Agregación" (usa tools) vs "Búsqueda" (usa RAG). Evita el conflicto de routing.

14. **Lista negra de patrones trampa.** Detectar preguntas con `proyecto nuevo`, `director`, `margen`, `IRPF`, `beneficio` y forzar plantilla "no dispongo" cuando no hay fuente explícita. Entrenar al router con los falsos positivos de Q13 y Q17.

15. **Re-evaluación después de fixes.** Re-ejecutar este cuestionario tras desplegar P0+P1 y publicar delta en `/admin/quality/summary`.

---

## 6. Conclusión ejecutiva

- **Puntuación global: 2,9/10** — el chat funciona como demostrador pero no como herramienta operativa.
- **3 patrones brillantes** (Q4 proveedor, Q14 honestidad, Q15 honestidad) muestran que el retrieval funciona cuando el contexto está bien segmentado.
- **2 alucinaciones graves** (Q13, Q17) son bloqueantes: invalidan cualquier اعتماد en respuestas con cifras.
- **5 "no sé" falsos** (Q1, Q6, Q7, Q11, Q12) indican que el motor de tools no se invoca cuando debería.
- **La confianza no discrimina** respuestas útiles de inútiles — el sistema no se puede gobernar por esa métrica.

**Recomendación:** no exponer el chat a usuarios finales sin antes implementar P0 (guard de alucinación + threshold + routing por tools). El camino crítico es corto: 4 tools nuevas + 1 post-procesado de importes + 1 fix de encoding = suficiente para llegar a 6-7/10 en la próxima vuelta de este mismo cuestionario.

---

*Generado automáticamente a partir de la sesión del 2026-07-17 sobre 31 documentos de muestra (de 198 totales) del hotel Gran Meliá de Mar, presupuestos 250052 a 251656.*
