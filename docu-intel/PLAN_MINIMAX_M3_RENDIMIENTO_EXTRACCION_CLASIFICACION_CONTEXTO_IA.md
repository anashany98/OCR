# Plan integral MiniMax M3: rendimiento de extracción, clasificación documental y respuestas IA con contexto

Fecha del contrato: 2026-07-13

Repositorio: C:\Users\Usuario\Desktop\OCR\OCR\docu-intel

Corpus real autorizado para pruebas: D:\TEST2025\2025\BON PLA SOCIEDAD ANONIMA

Ejecutor previsto: MiniMax M3

Estado: contrato de implementación, validación y cierre

---

## 1. Mandato

MiniMax M3 debe implementar este plan completo, de forma continua y en el orden indicado. No debe limitarse a proponer cambios ni declarar una fase terminada porque el código compile.

El objetivo es cerrar conjuntamente estos problemas:

1. La extracción estructurada es demasiado lenta y puede bloquear trabajo que debería quedar disponible antes.
2. La respuesta de IA tarda demasiado, aunque la interfaz use streaming.
3. La clasificación confunde el formato físico del archivo, el tipo documental de negocio y su contenido visual.
4. Las respuestas de IA no siempre aprovechan de forma óptima el contexto ya encontrado.
5. Faltan métricas reproducibles que separen recuperación, preparación de contexto, espera del modelo y generación.
6. Existe infraestructura ya construida, como la caché de respuestas y el aprendizaje de correcciones, que no está completamente integrada en el camino de ejecución.

La implementación debe conservar compatibilidad, aislamiento por permisos, trazabilidad, citas, idempotencia y todos los cambios locales que ya existen.

---

## 2. Resultado esperado

Al finalizar, la aplicación debe cumplir simultáneamente:

- Un documento puede quedar con texto buscable y disponible para chat sin esperar a la extracción enriquecida.
- La extracción enriquecida se ejecuta solamente cuando aporta valor y no se repite si entrada, modelo, prompt y esquema no han cambiado.
- La clasificación distingue formato de origen, tipo documental de negocio, subtipo y etiquetas de contenido.
- Las correcciones humanas alimentan el mecanismo de aprendizaje existente.
- El chat devuelve inmediatamente un evento de progreso, recupera primero pruebas exactas o estructuradas y usa búsqueda semántica costosa sólo cuando hace falta.
- La caché de respuestas se consulta, respeta usuario, tenant y alcance documental, y se invalida cuando cambia el conocimiento subyacente.
- El modelo recibe un paquete de contexto más pequeño, priorizado y explícito.
- Los prompts se versionan y se evalúan contra preguntas reales, conflictos, OCR deficiente, ausencia de evidencia e intentos de inyección.
- Existe una comparación antes/después reproducible sobre el mismo corpus.
- No queda ninguna regresión de permisos, citas, alcance o calidad.

---

## 3. Reglas obligatorias de ejecución

### 3.1 Antes de tocar código

1. Leer íntegramente este archivo.
2. Leer íntegramente AGENTS.md y cualquier AGENTS.md más específico que afecte a un archivo.
3. Ejecutar:

       git status --short --branch
       git log -10 --oneline
       docker compose config --services

4. Inventariar los cambios locales existentes y no sobrescribirlos.
5. Confirmar servicios, modelos configurados y migración actual sin mostrar secretos.
6. Revisar primero los archivos citados en cada fase.
7. Si Graphify está disponible, usarlo para las consultas de arquitectura. En la inspección previa el ejecutable no estuvo disponible; su ausencia no es un bloqueo y se debe continuar con rg e inspección dirigida.

### 3.2 Conservación y Git

- Prohibido usar git reset --hard, git clean, git checkout --, restauraciones masivas o cualquier operación destructiva.
- No modificar, borrar, mover ni incluir en commits cambios locales ajenos al plan.
- Antes de editar un archivo ya modificado, inspeccionar su diff y fusionar el cambio con cuidado.
- Hacer un commit pequeño por tarea coherente, sólo después de verificarla.
- Añadir al staging únicamente rutas de la tarea actual.
- No hacer amend de commits previos salvo instrucción expresa del usuario.
- No subir documentos del corpus, OCR completo, credenciales, PII ni contenido empresarial a Git.

### 3.3 Compatibilidad

- No romper BaseOCREngine.
- No romper firmas públicas de embed o search.
- Mantener compatibilidad transitoria para document_type y contratos API existentes.
- Toda migración debe tener upgrade, downgrade, prueba sobre base vacía y prueba sobre datos existentes.
- No introducir un segundo sistema paralelo de aprendizaje si ClassificationSuggestion y LearnedPattern ya cubren el caso.
- No sustituir un fallo real por un fallback silencioso que haga parecer correcto el sistema.

### 3.4 Seguridad

- Todo acceso exacto, estructurado, semántico o por caché debe aplicar permisos antes de recuperar datos.
- La clave de caché debe incluir identidad y alcance efectivo, no sólo la pregunta.
- No registrar contenido completo de documentos, prompts privados, tokens, contraseñas ni datos bancarios.
- Las métricas deben usar etiquetas de cardinalidad acotada; nunca document_id, filename, user_id ni texto de consulta como label.
- Los artefactos de auditoría que se guarden en el repositorio deben estar anonimizados.

### 3.5 Continuidad

MiniMax M3 debe continuar de una fase a la siguiente sin esperar mensajes de “continúa”. Sólo debe detenerse por un bloqueo real que no pueda resolver de forma segura, por ejemplo:

- credenciales o hardware imprescindible realmente ausente;
- una decisión de producto irreversible con dos comportamientos incompatibles;
- riesgo de pérdida de datos;
- fallo de permisos que impida validar sin ampliar autorizaciones.

Una prueba lenta, una cobertura difícil, un warning de lint o la necesidad de investigar no son motivos para detenerse.

---

## 4. Evidencia inicial ya observada

Esta evidencia orienta el trabajo, pero MiniMax M3 debe repetirla mediante el benchmark de FASE 0 antes de usarla como resultado final.

### 4.1 Corpus BON PLA

- 28 archivos encontrados.
- 27 documentos únicos y 1 duplicado.
- Los 27 documentos no duplicados llegaron a tener texto OCR.
- text_search_ready: 27 de 27.
- semantic_search_ready: 27 de 27.
- needs_reembedding: 0.
- Confianza OCR media por página observada: 0,616.
- Documentos con OCR bajo: 5.
- Documentos marcados needs_review: 7.
- No quedaron trabajos activos pendientes o procesándose al cerrar la prueba.

### 4.2 Extracción estructurada observada

Muestra inicial de seis ejecuciones:

| Ejecución | Tiempo | Resultado |
|---|---:|---|
| 1 | 21,584 s | Correcto |
| 2 | 32,121 s | Correcto |
| 3 | 16,123 s | Correcto |
| 4 | 47,159 s | JSON inválido |
| 5 | 17,020 s | Correcto |
| 6 | 14,697 s | Correcto |

Mediana aproximada: 19,3 s.

Rango observado: 14,7 a 47,2 s.
Después de limitar la salida del prompt, el documento fallido de seis páginas terminó correctamente en 24,314 s.

Esto demuestra que compilar no basta: hay variabilidad alta, generación excesiva y posibilidad de JSON truncado o inválido.

### 4.3 Chat observado

Tres preguntas reales produjeron respuestas factualmente correctas después de correcciones previas:

1. Identificación de Aitor Hermosel y condición del 40 % pagadero antes del 10 de marzo.
2. Identificación de los albaranes 012770 como entrega y 012769 como recogida.
3. Relación del JPEG de presupuesto firmado con HOSTAL ANIBAL 2 FASE, BON PLA SOCIEDAD ANONIMA y aceptación del 23/06/2024.

Tiempos de pared observados:

- 97,7 s.
- 90,9 s.
- 73,5 s.
- Mediana aproximada: 90,9 s.

Advertencia: estas consultas se lanzaron desde procesos Python nuevos dentro del contenedor y pudieron incluir carga en frío del reranker o del cliente. No equivalen por sí solas a la experiencia de una API caliente. FASE 0 debe medir por los endpoints autenticados /api/v1/ai/ask y /api/v1/ai/ask/stream, distinguiendo frío y caliente.

### 4.4 Casos de clasificación que motivan el plan

Los siguientes errores reales muestran que una única etiqueta está mezclando conceptos diferentes:

| Archivo o patrón | Clasificación problemática | Interpretación esperada |
|---|---|---|
| HOSTAL ANIBAL IBIZA.msg | foto_producto | Formato email; contenido comercial o de obra según cuerpo y adjuntos |
| Re_ PEDIDO PROVEEDOR.msg | foto_producto | Email; intención pedido a proveedor |
| HOSTAL ANIBAL CARPINTERIA 2.xlsx | foto_producto | Hoja de cálculo; medición, coste o carpintería |
| ppto aceptado...jpeg | foto_producto | Escaneo o imagen de presupuesto aceptado |
| ppto firmado.jpeg | foto_producto | Escaneo o imagen de presupuesto firmado |
| incidencia sillas.pdf | foto_producto | Incidencia, parte de trabajo o comunicación técnica |
| medición 2 armarios.docx | foto_producto | Documento de medición |

La solución no debe ser añadir excepciones sin límite. Debe separar dimensiones y conservar evidencia explicable.

---

## 5. Diagnóstico técnico que debe confirmarse

### 5.1 Extracción

Archivos iniciales:

- backend/app/services/hyperextract/service.py
- backend/app/services/document_processing_core.py
- backend/app/services/quality.py
- backend/app/services/metrics/pipeline.py
- backend/app/services/metrics/_registry.py

Hallazgos:

- El prompt puede incluir hasta aproximadamente 32.000 caracteres.
- La llamada crea un cliente HTTP por ejecución.
- No hay garantía universal de max_tokens compacto ni de salida JSON estructurada negociada con el proveedor.
- Un JSON truncado puede invalidar todo el resultado.
- HyperExtract puede ejecutarse desde el pipeline principal si hyperextract_run_in_pipeline está activo.
- Una reclasificación puede repetir extracción cara si no existe una huella de idempotencia suficiente.
- La disponibilidad para búsqueda no debe depender de la extracción enriquecida.

### 5.2 Chat y recuperación

Archivos iniciales:

- backend/app/ai/context.py
- backend/app/ai/multi_query.py
- backend/app/services/search_service.py
- backend/app/ai/local_answer.py
- backend/app/ai/agent.py
- backend/app/api/routes/ai.py
- backend/app/services/ai_cache.py
- backend/app/ai/prompts.py
- backend/app/services/metrics/rag.py

Hallazgos:

- collect_context puede ejecutar variantes de consulta de forma secuencial.
- Cada búsqueda híbrida ya incluye texto, semántica, BM25, reranking y MMR; repetirla completa por cada variante multiplica el coste.
- El endpoint streaming prepara contexto y snapshots antes de emitir el primer evento útil.
- La caché tiene lectura exacta y semántica implementada, pero los caminos principales observados escriben al final sin usar claramente get_cached_answer al inicio.
- La generación usa presupuestos que pueden llegar a 4.000 tokens incluso para preguntas factuales cortas.
- El fallback de Qwen ante respuesta vacía puede repetir una generación completa.
- El mismo modelo general se usa en tareas con necesidades distintas.

### 5.3 Prompts y contexto

Hallazgos:

- El prompt del chat ya contiene reglas importantes, pero es largo y compartido entre preguntas simples y síntesis complejas.
- El contexto para LLM se limita por número de elementos y caracteres, no siempre por valor probatorio.
- Una coincidencia exacta debería pesar más que fragmentos semánticos redundantes.
- Los metadatos, campos estructurados, OCR y fragmentos deben presentarse con origen y prioridad claros.
- Debe distinguirse evidencia literal, inferencia y ausencia de prueba.

### 5.4 Clasificación

Archivos iniciales:

- backend/app/services/classification.py
- backend/app/api/routes/documents.py
- backend/app/models/learning.py
- backend/app/workers/learning_tasks.py

Hallazgos:

- Se mezclan formato contenedor, tipo de negocio y contenido visual.
- Ya existen ClassificationSuggestion y LearnedPattern; deben aprovecharse.
- El endpoint de reclasificación debe comprobarse porque asigna classification_confidence mientras el modelo Document usa confidence.
- Las extensiones MSG, EML, XLSX, DOCX, JPEG y PDF no deberían competir en el mismo nivel semántico con presupuesto, pedido, incidencia o medición.

---

## 6. Arquitectura objetivo

Flujo documental:

    registro
      -> detección de formato y seguridad
      -> extracción determinista o OCR
      -> text_ready
      -> índice léxico y disponibilidad inicial para chat
      -> clasificación multidimensional explicable
      -> extracción enriquecida asíncrona e idempotente
      -> embeddings
      -> search_ready
      -> enriquecimientos posteriores

Flujo de chat:

    autenticación y alcance
      -> lectura de caché aislada
      -> resolución de referencias y coincidencia exacta
      -> consulta estructurada
      -> búsqueda híbrida selectiva
      -> reranking sólo cuando aporta valor
      -> empaquetado de contexto por evidencia
      -> routing de modelo y prompt
      -> SSE inmediato
      -> respuesta citada
      -> persistencia y caché

Modelo de clasificación:

| Dimensión | Ejemplos | Regla |
|---|---|---|
| source_format | email, spreadsheet, word, pdf, image, dxf | Se deriva de formato real, extensión validada y parser |
| document_type | presupuesto, pedido, albarán, factura, incidencia, medición | Describe el tipo de negocio |
| document_subtype | firmado, aceptado, proveedor, recogida, entrega | Especifica el estado o variante |
| content_tags | carpintería, mobiliario, plano, fotografías, obra | Son etiquetas múltiples, no tipo primario |
| classification_evidence | filename, MIME, parser, regla, campo, modelo | Explica por qué se eligió la clase |

Durante la transición, document_type debe seguir siendo utilizable por clientes existentes.

---

## 7. Indicadores y umbrales de aceptación

Los valores se miden en hardware y configuración local documentados, con el mismo corpus y al menos cinco repeticiones calientes por escenario.

### 7.1 Extracción

| Métrica | Objetivo mínimo |
|---|---:|
| Éxito estructurado en documentos compatibles | >= 98 % |
| JSON inválido o truncado | <= 1 % |
| Extracción enriquecida, documentos de hasta 10 páginas, p50 caliente | <= 8 s |
| Extracción enriquecida, documentos de hasta 10 páginas, p95 caliente | <= 20 s |
| Reejecuciones sin cambio de huella | 0 llamadas al modelo |
| Tiempo hasta text_ready | No bloqueado por HyperExtract |

Si el hardware no permite el umbral absoluto, sigue siendo obligatorio demostrar una mejora mínima del 50 % en p50 y del 40 % en p95 frente a la línea base reproducida.

### 7.2 Chat

| Métrica | Objetivo mínimo |
|---|---:|
| Primer evento SSE p95 | <= 300 ms |
| Recuperación simple p95 caliente | <= 2 s |
| Primer token visible p95 caliente | <= 5 s |
| Respuesta factual simple completa p50 | <= 15 s |
| Respuesta factual simple completa p95 | <= 25 s |
| Respuesta compleja completa p95 | <= 35 s |
| Respuesta repetida válida desde caché p95 | <= 1 s |
| Exactitud factual en conjunto dorado | >= 95 % |
| Precisión de citas | 100 % |
| Abstención correcta sin evidencia | 100 % |

### 7.3 Clasificación

| Métrica | Objetivo mínimo |
|---|---:|
| source_format en extensiones críticas | 100 % |
| Macro F1 de document_type en conjunto revisado | >= 0,90 |
| Casos críticos clasificados erróneamente como foto_producto | 0 |
| Correcciones con evidencia persistida | 100 % |
| Reclasificación sin repetir OCR o extracción innecesaria | 100 % |

### 7.4 Seguridad y estabilidad

| Métrica | Objetivo |
|---|---:|
| Accesos cruzados entre tenants o alcances | 0 |
| Fugas a través de caché exacta o semántica | 0 |
| Citas de documentos no autorizados | 0 |
| Trabajos duplicados tras reintento o reinicio | 0 |
| Pendientes sin explicación al cerrar certificación | 0 |

---

## 8. Orden de ejecución

El orden es obligatorio:

1. FASE 0 — Línea base reproducible.
2. FASE 1 — Instrumentación y trazabilidad.
3. FASE 2 — Auditoría real y rediseño de clasificación.
4. FASE 3 — Rendimiento e idempotencia de extracción.
5. FASE 4 — Velocidad del chat y recuperación.
6. FASE 5 — Prompts, contexto y calidad factual.
7. FASE 6 — Percepción de velocidad en frontend.
8. FASE 7 — Seguridad, regresión y carga.
9. FASE 8 — Certificación final y despliegue controlado.

No optimizar prompts antes de saber dónde se consume el tiempo. No activar caché antes de demostrar aislamiento. No ejecutar backfills antes de disponer de dry-run y conteos.

---

## FASE 0 — Línea base reproducible y conjunto de evaluación

### Objetivo

Construir una medición repetible que separe tiempo en frío, tiempo caliente, recuperación, primer evento, primer token, generación y extracción.

### Tareas

#### 0.1 Inventario operativo

- Registrar commit actual, rama y estado sin modificar cambios existentes.
- Registrar CPU, RAM, GPU, VRAM, versión del driver y contenedores.
- Registrar proveedor y nombres de modelos sin guardar claves.
- Registrar valores relevantes en forma enmascarada:
  - ai_request_timeout_seconds;
  - ai_max_context_tokens;
  - hyperextract_timeout_seconds;
  - hyperextract_run_in_pipeline;
  - modelos de chat, visión, embeddings y reranker;
  - concurrencia de workers y rutas de colas.
- Confirmar health de backend, PostgreSQL, Redis, workers y servidor de modelos.

#### 0.2 Herramienta de benchmark

Crear scripts/benchmark_ai_pipeline.py con:

- autenticación mediante usuario de prueba autorizado o token suministrado por entorno;
- selección explícita de tenant y alcance;
- llamadas a /api/v1/ai/ask y /api/v1/ai/ask/stream;
- captura de:
  - DNS o conexión cuando aplique;
  - tiempo al primer evento SSE;
  - tiempo al primer delta;
  - tiempo total;
  - códigos y errores;
  - fuentes recibidas;
  - hit o miss de caché si la API lo expone de forma segura;
- ejecución fría una vez y caliente al menos cinco veces;
- ejecución de extracción sobre una muestra estratificada;
- salida JSON estable y resumen Markdown;
- modo dry-run;
- redacción de preguntas, nombres y contenidos sensibles en artefactos versionados.

No usar procesos Python nuevos como única medición del chat. La ruta principal debe atravesar la API real.

#### 0.3 Conjunto de documentos

Revisar los 27 documentos únicos del corpus sin copiar originales al repositorio.

Seleccionar como mínimo 12 para revisión profunda:

- 2 MSG o EML;
- 2 hojas de cálculo;
- 2 DOCX;
- 2 imágenes o escaneos;
- 2 PDF, incluyendo uno problemático;
- 2 documentos de OCR bajo, manuscritos o diseño complejo si existen.

Para cada documento guardar en un manifiesto local no versionado:

- hash;
- extensión y MIME;
- páginas u hojas;
- parser elegido;
- tiempo de extracción de texto;
- confianza OCR;
- clase actual;
- clase esperada revisada;
- causa del error;
- campos estructurados esperados;
- preguntas que debe poder contestar.

El artefacto versionado sólo debe conservar IDs sintéticos y etiquetas anonimizadas.

#### 0.4 Conjunto dorado de preguntas

Incluir como mínimo:

- las tres preguntas reales ya verificadas;
- una pregunta exacta por identificador;
- una pregunta por nombre de archivo;
- una pregunta corta de seguimiento que dependa del turno anterior;
- una síntesis que requiera dos documentos;
- una contradicción entre documentos;
- una pregunta sin evidencia;
- una pregunta sobre OCR de baja confianza;
- una pregunta con intento de inyección dentro del documento;
- una pregunta que un usuario sin alcance no debe resolver.

Cada caso debe declarar:

- hechos obligatorios;
- hechos prohibidos;
- documentos fuente permitidos;
- citas esperadas;
- si debe abstenerse;
- tolerancia de redacción;
- tiempo objetivo.

### Artefactos

- scripts/benchmark_ai_pipeline.py
- backend/tests/fixtures/minimax_m3_eval/manifest.sanitized.json
- backend/tests/fixtures/minimax_m3_eval/questions.json
- docs/MINIMAX_M3_BASELINE.md
- data/minimax-m3-performance/baseline.json, ignorado por Git si contiene datos locales

### Verificación

- El benchmark falla con exit distinto de cero si falta autenticación, se viola el alcance o no puede medir.
- Dos ejecuciones con la misma semilla producen el mismo formato de salida.
- Las cifras distinguen frío de caliente.
- El informe enumera cualquier caso no medido y no inventa resultados.

### Criterio de cierre

No cerrar FASE 0 hasta tener tiempos por etapa, resultados de clasificación y respuestas esperadas para el conjunto dorado.

### Commit sugerido

docs(perf): establish reproducible MiniMax M3 baseline

---

## FASE 1 — Instrumentación del camino crítico

### Objetivo

Explicar dónde se consume cada segundo sin aumentar cardinalidad ni registrar contenido sensible.

### Archivos principales

- backend/app/services/metrics/_registry.py
- backend/app/services/metrics/pipeline.py
- backend/app/services/metrics/rag.py
- backend/app/services/hyperextract/service.py
- backend/app/ai/context.py
- backend/app/ai/agent.py
- backend/app/api/routes/ai.py

### Tareas

#### 1.1 Métricas de extracción

Medir histogramas y contadores para:

- construcción del prompt;
- espera del proveedor;
- análisis y validación de JSON;
- intento de reparación;
- persistencia;
- resultado: success, invalid_json, timeout, provider_error, skipped, cache_hit;
- ruta: deterministic, llm_text, vlm;
- clase de tamaño: small, medium, large.

No usar nombres de archivo ni IDs como etiquetas.

#### 1.2 Métricas de chat

Medir:

- cache_lookup;
- reference_resolution;
- exact_search;
- structured_search;
- semantic_search;
- hybrid_search;
- reranker;
- context_pack;
- prompt_build;
- model_queue;
- time_to_first_event;
- time_to_first_token;
- generation;
- persistence;
- total;
- prompt_tokens y completion_tokens si el proveedor los devuelve;
- número de variantes, candidatos, fuentes y reintentos en buckets acotados.

#### 1.3 Trazas estructuradas

- Crear un correlation_id por solicitud.
- Permitir unir log de API, recuperación y proveedor.
- No incluir texto de consulta ni contenido.
- Incorporar un resumen de timings al evento final sólo en modo diagnóstico autorizado.

#### 1.4 Pruebas

- Comprobar que las métricas se emiten en éxito, fallo y cancelación.
- Comprobar que no contienen etiquetas de alta cardinalidad.
- Comprobar que una excepción no impide cerrar el temporizador total.

### Criterio de cierre

Para cada pregunta del conjunto dorado debe poder explicarse el tiempo total como suma de etapas principales con un margen razonable.

### Commit sugerido

feat(metrics): trace extraction and AI response latency

---

## FASE 2 — Auditoría real y clasificación multidimensional

### Objetivo

Corregir la causa arquitectónica de las clasificaciones erróneas, no sólo los siete nombres conocidos.

### Archivos principales

- backend/app/services/classification.py
- backend/app/api/routes/documents.py
- backend/app/models/document.py
- backend/app/models/learning.py
- backend/app/workers/learning_tasks.py
- backend/tests/test_classification.py

### Tareas

#### 2.1 Revisión documental explicada

Revisar los 27 documentos y documentar en docs/MINIMAX_M3_CLASSIFICATION_AUDIT_BON_PLA.md:

- distribución por formato;
- distribución por tipo de negocio;
- matriz de confusión;
- casos correctos e incorrectos;
- regla o señal que ganó;
- señal que debería haber ganado;
- calidad de OCR;
- posible impacto sobre extracción y chat.

No copiar texto completo. Anonimizar importes, personas, cuentas, NIF y direcciones.

#### 2.2 Modelo de datos

Añadir, si no existen equivalentes:

- source_format;
- document_subtype;
- content_tags;
- classification_evidence;
- classifier_version;
- classified_at.

Mantener document_type como tipo de negocio y compatibilidad con API.

Antes de migrar:

- inspeccionar esquema real y migración head;
- comprobar si existen columnas equivalentes;
- definir defaults seguros;
- probar upgrade y downgrade.

#### 2.3 Clasificador por capas

Orden obligatorio:

1. Detectar source_format con extensión validada, MIME y firma del archivo.
2. Extraer señales deterministas del nombre y metadatos.
3. Extraer señales del parser y campos estructurados.
4. Aplicar reglas aprendidas aprobadas.
5. Resolver document_type y subtype con puntuaciones explicables.
6. Añadir content_tags múltiples.
7. Usar LLM sólo como sugerencia cuando haya conflicto o confianza baja.
8. Enviar casos dudosos a revisión sin convertir la sugerencia en verdad automática.

Un MSG nunca debe convertirse en foto como formato. Puede ser source_format=email y content_tags=fotografías si contiene imágenes.

#### 2.4 Reutilizar aprendizaje existente

- Conectar correcciones a ClassificationSuggestion.
- Requerir aprobación según roles existentes.
- Materializar LearnedPattern sólo desde sugerencias aprobadas.
- Invalidar la caché de clasificación afectada.
- Registrar versión de regla y evidencia.
- Evitar reglas globales derivadas de una única empresa cuando no generalicen.

#### 2.5 Corregir reclasificación

Verificar y corregir backend/app/api/routes/documents.py para persistir el campo real confidence en lugar de un atributo no mapeado.

Añadir pruebas que vuelvan a leer el documento desde otra sesión de base de datos.

#### 2.6 Backfill seguro

- Crear modo dry-run con conteos old -> new.
- No ejecutar OCR ni HyperExtract por reclasificar.
- Actualizar sólo filas cuya versión o huella de clasificación cambie.
- Procesar por lotes y con reanudación.
- Crear copia de seguridad de datos antes de ejecutar sobre el corpus.

### Pruebas mínimas

- MSG y EML conservan source_format=email.
- XLSX conserva source_format=spreadsheet.
- DOCX conserva source_format=word.
- JPEG de presupuesto se clasifica como presupuesto sin perder source_format=image.
- PDF de incidencia no se clasifica como foto por contener imágenes.
- Documento de medición no se clasifica como foto.
- Una corrección aprobada se aprende.
- Una corrección rechazada no modifica reglas.
- Dos tenants con patrones diferentes no se contaminan.
- Reclasificar dos veces no relanza OCR ni extracción.
- confidence persiste tras cerrar y reabrir sesión.

### Criterio de cierre

Cumplir los objetivos de clasificación de la sección 7 y publicar la matriz de confusión antes/después.

### Commits sugeridos

1. feat(classification): separate source format from business type
2. fix(classification): persist reclassification confidence
3. feat(classification): backfill versioned classification safely

---

## FASE 3 — Extracción rápida, selectiva e idempotente

### Objetivo

Reducir latencia y fallos sin perder campos útiles, y sacar HyperExtract del camino que bloquea text_ready.

### Archivos principales

- backend/app/services/hyperextract/service.py
- backend/app/services/document_processing_core.py
- backend/app/services/quality.py
- configuración y modelos relacionados con extracción
- workers y rutas de colas

### Tareas

#### 3.1 Separar estados

Garantizar esta secuencia:

- registered;
- text_ready;
- search_ready;
- enriched.

La extracción determinista necesaria para búsqueda puede ejecutarse antes. HyperExtract debe ser enriquecimiento asíncrono salvo que un contrato concreto lo exija.

Una avería del modelo no debe devolver el documento a un estado que impida buscar su texto ya válido.

#### 3.2 Huella de extracción

Persistir una huella formada por:

- hash del texto o entrada visual normalizada;
- document_type y classifier_version;
- proveedor;
- modelo;
- versión de prompt;
- versión de esquema;
- versión del extractor.

Si la huella no cambia y existe resultado válido:

- no llamar al modelo;
- registrar skipped o cache_hit;
- reutilizar el resultado.

La opción force debe ser explícita, autorizada y auditable.

#### 3.3 Selección de ruta

- MSG, EML, XLSX, DOCX y PDF digital: parser y extracción determinista primero.
- Imágenes, manuscritos y PDF escaneado: OCR o VLM sólo cuando haga falta.
- Campos simples conocidos: reglas deterministas o esquemas compactos.
- LLM de texto rápido: documentos limpios con texto suficiente.
- VLM: sólo cuando la estructura visual o baja confianza lo justifique.
- Modelo más capaz: sólo para casos difíciles medidos.

No elegir modelo por reputación. Comparar los modelos locales disponibles sobre la misma muestra y documentar latencia, precisión, VRAM y fallos.

#### 3.4 Cliente de proveedor

- Reutilizar cliente HTTP con keep-alive y límites de conexiones.
- Definir timeouts separados de conexión, lectura y total.
- Cerrar el cliente en shutdown.
- Controlar concurrencia para no saturar GPU.
- Añadir circuit breaker o backoff acotado para fallos transitorios.

#### 3.5 Salida estructurada y prompts compactos

- Detectar capacidades del proveedor al arranque o mediante prueba controlada.
- Usar response_format o JSON schema cuando sea compatible.
- Definir max_tokens por esquema y tipo documental.
- Reducir el contexto al fragmento relevante y conservar referencias.
- Usar plantillas específicas por tipo.
- Limitar campos, entidades y relaciones a lo requerido.
- Validar con Pydantic.
- Ante JSON inválido, intentar una reparación acotada una sola vez usando la salida parcial; no regenerar siempre todo el documento.

#### 3.6 Colas

- Separar extracción enriquecida de tareas interactivas.
- Priorizar chat sobre backfill y enriquecimiento.
- Aplicar límites por GPU y tipo de tarea.
- Medir antes de añadir workers.
- Un reinicio debe reanudar sin duplicar resultados.

#### 3.7 Pruebas

- text_ready ocurre antes de terminar HyperExtract.
- clasificación-only no ejecuta HyperExtract.
- misma huella produce cero llamadas adicionales.
- cambio de esquema produce una ejecución.
- timeout conserva texto e índice válidos.
- JSON inválido se repara una vez y luego falla de forma explícita.
- proveedor sin JSON schema usa fallback validado, no silencioso.
- no se envía una imagen enorme fuera de límites.
- reintento y reinicio no duplican filas.

### Criterio de cierre

Cumplir objetivos de extracción, conservar calidad del conjunto dorado y demostrar que búsqueda y chat pueden usar el documento antes del enriquecimiento.

### Commits sugeridos

1. refactor(pipeline): decouple searchable text from enrichment
2. feat(extraction): fingerprint and reuse structured results
3. perf(extraction): pool clients and constrain structured output
4. perf(workers): isolate interactive and enrichment workloads

---

## FASE 4 — Velocidad real del chat

### Objetivo

Reducir el trabajo previo al primer token y evitar búsquedas o generaciones redundantes.

### Archivos principales

- backend/app/services/ai_cache.py
- backend/app/api/routes/ai.py
- backend/app/ai/agent.py
- backend/app/ai/context.py
- backend/app/ai/multi_query.py
- backend/app/services/search_service.py
- backend/app/ai/local_answer.py

### Tareas

#### 4.1 Lectura de caché

Integrar get_cached_answer al inicio de rutas streaming y no streaming.

La identidad de caché debe incluir como mínimo:

- tenant;
- usuario o conjunto de permisos efectivos;
- IDs o versión del alcance documental;
- modo de consulta;
- pregunta normalizada;
- contexto conversacional necesario;
- modelo;
- versión de prompt;
- versión de índice o conocimiento.

Una coincidencia semántica nunca debe ampliar alcance.

Invalidar o versionar al cambiar:

- documento;
- texto OCR;
- extracción;
- clasificación relevante;
- embeddings;
- permisos;
- prompt;
- modelo.

#### 4.2 SSE inmediato

El endpoint /api/v1/ai/ask/stream debe:

1. validar autenticación y payload;
2. abrir stream;
3. emitir start en <= 300 ms;
4. emitir estados acotados: cache, exact_search, retrieval, context, generation;
5. comenzar generación;
6. emitir deltas;
7. emitir fuentes y resultado final.

La preparación de snapshots costosos no debe retrasar el primer evento. Puede terminar al final si no altera autorización.

#### 4.3 Recuperación adaptativa

Orden:

1. referencia de turno o documento;
2. identificador, nombre de archivo y coincidencia exacta;
3. campos estructurados;
4. búsqueda léxica;
5. búsqueda híbrida;
6. variantes y reranking sólo si la evidencia sigue siendo insuficiente.

Si hay una coincidencia exacta fuerte y suficiente:

- no generar tres variantes;
- no rerankear todo el corpus;
- no ejecutar búsqueda semántica innecesaria.

Limitar por defecto a dos variantes adicionales y ejecutarlas en paralelo sólo cuando el backend y la GPU lo soporten. Deduplicar antes del reranker.

#### 4.4 Reranker

- Mantenerlo caliente si su coste amortizado lo justifica.
- No cargarlo por consulta.
- Saltarlo bajo un umbral pequeño de candidatos o ante evidencia exacta.
- Registrar cuánto mejora NDCG o recall frente a su coste.
- Retirarlo del camino simple si no aporta una mejora medible.

#### 4.5 Routing de modelo

Definir perfiles medidos:

- factual_exact: respuesta corta, contexto pequeño, modelo rápido;
- factual_multi_source: modelo rápido con algo más de presupuesto;
- synthesis_complex: modelo capaz;
- low_ocr_visual: ruta visual cuando sea necesaria;
- extraction_json: perfil estructurado independiente del chat.

Presupuestos iniciales a validar:

- 400 a 700 tokens para hechos simples;
- hasta 1.200 para síntesis;
- 4.000 sólo mediante justificación explícita.

Evitar una segunda generación completa por respuesta vacía. Primero detectar configuración de thinking, protocolo y stop tokens.

#### 4.6 Cliente y cancelación

- Reutilizar cliente asíncrono.
- Propagar cancelación del navegador hasta búsqueda y proveedor.
- Definir timeout por etapa.
- No persistir como respuesta completa una generación cancelada.
- Liberar semáforos y conexiones siempre.

### Pruebas mínimas

- Cache hit exacto no llama a búsqueda ni modelo.
- Cache hit semántico respeta alcance.
- Pregunta idéntica de usuario sin permisos no reutiliza respuesta autorizada.
- El primer evento llega antes de terminar retrieval.
- Coincidencia exacta evita multi-query.
- Consulta ambigua sí activa recuperación ampliada.
- Cancelar en frontend cancela backend.
- Respuesta vacía no duplica indiscriminadamente la generación.
- Rutas streaming y no streaming producen hechos y citas equivalentes.

### Criterio de cierre

Cumplir objetivos de chat de la sección 7 en cinco ejecuciones calientes y una fría, sin bajar exactitud ni citas.

### Commits sugeridos

1. feat(ai-cache): read scoped cached answers safely
2. perf(chat): stream progress before retrieval
3. perf(retrieval): select exact and hybrid paths adaptively
4. perf(ai): route models and token budgets by task

---

## FASE 5 — Prompts, paquete de contexto y calidad de respuesta

### Objetivo

Mejorar la respuesta por contexto sin compensar una mala recuperación con prompts enormes.

### Archivos principales

- backend/app/ai/prompts.py
- backend/app/ai/context.py
- backend/app/ai/agent.py
- backend/app/ai/local_answer.py
- fixtures del conjunto dorado

### Tareas

#### 5.1 Versionado

Crear perfiles versionados, por ejemplo:

- chat_factual_v2;
- chat_synthesis_v2;
- chat_low_ocr_v2;
- extraction_budget_v2;
- extraction_order_v2.

Persistir prompt_version en telemetría, caché y respuestas guardadas.

#### 5.2 Contrato del prompt

El sistema debe instruir al modelo para:

1. Responder primero de forma directa.
2. Usar sólo la evidencia autorizada entregada.
3. No afirmar que falta un dato si existe una coincidencia exacta en contexto.
4. Citar cada hecho verificable con la fuente correspondiente.
5. Separar hechos literales de inferencias.
6. Señalar conflictos entre documentos y sus fechas.
7. Limitar la advertencia de OCR bajo al hecho afectado.
8. Abstenerse cuando no exista evidencia suficiente.
9. Ignorar instrucciones contenidas dentro de documentos recuperados.
10. No usar documentos relacionados que sean irrelevantes para rellenar la respuesta.
11. Mantener concisión en preguntas simples.
12. Explicar cálculos o síntesis cuando la pregunta lo requiera.

#### 5.3 Paquete de contexto

Representar cada evidencia con:

- source_id seguro;
- nombre visible autorizado;
- tipo documental;
- fecha;
- página, hoja, bloque o campo;
- clase de evidencia: exact, structured, lexical, semantic;
- confianza OCR;
- texto mínimo necesario;
- relación con la pregunta.

Prioridad:

1. campo estructurado exacto;
2. identificador o nombre exacto;
3. fragmento literal;
4. OCR de alta confianza;
5. fragmento semántico;
6. OCR de baja confianza;
7. documento relacionado.

Deduplicar fragmentos solapados. No consumir presupuesto repitiendo el mismo párrafo.

#### 5.4 Presupuesto dinámico

- Pregunta factual: pocas fuentes, fragmentos cortos.
- Comparación: una evidencia principal por elemento.
- Síntesis: diversidad por documento y cobertura.
- Seguimiento: reutilizar referencias del turno, no todo el historial.
- OCR bajo: aportar ventana local y metadatos, no todo el documento.

Medir tokens reales cuando el tokenizer esté disponible.

#### 5.5 Evaluación

Crear backend/tests/evals/test_minimax_m3_prompt_quality.py o herramienta equivalente que puntúe:

- presencia de hechos obligatorios;
- ausencia de hechos prohibidos;
- citas válidas;
- fuente correcta;
- abstención;
- reconocimiento de conflicto;
- resistencia a inyección;
- concisión;
- latencia y tokens.

No usar exclusivamente otro LLM como juez. Los identificadores, fechas, porcentajes, nombres y citas deben validarse de forma determinista.

Ejecutar comparación A/B entre prompt actual y candidato sobre el mismo contexto congelado.

El nuevo prompt sólo gana si:

- no reduce exactitud;
- mejora o mantiene citas;
- reduce tokens o tiempo;
- no empeora abstención ni seguridad.

### Criterio de cierre

Exactitud >= 95 %, citas 100 %, abstención 100 % y mejora medible en tokens o latencia.

### Commits sugeridos

1. feat(prompts): version task-specific AI instructions
2. feat(context): pack evidence by relevance and confidence
3. test(ai): add deterministic grounded-answer evaluations

---

## FASE 6 — Velocidad percibida y control en frontend

### Objetivo

Hacer visible el progreso real, permitir cancelar y evitar la sensación de bloqueo.

### Archivos principales

- frontend/src/api/ai.ts
- frontend/src/pages/chat/useChat.ts
- componentes de chat relacionados

### Tareas

- Mostrar estados recibidos por SSE:
  - comprobando caché;
  - buscando coincidencias;
  - reuniendo contexto;
  - generando respuesta.
- Mostrar el primer estado en cuanto llegue start.
- Añadir AbortController de extremo a extremo.
- Permitir detener una respuesta.
- Diferenciar timeout, cancelación, error de recuperación y error de modelo.
- Conservar respuesta parcial sólo si se etiqueta como incompleta.
- Actualizar fuentes de forma estable al evento final.
- No provocar refresh completo de la página.
- Evitar duplicar mensajes tras reconexión.
- Registrar Web Vitals o tiempos locales sin contenido sensible.

### Pruebas

- start cambia el estado inmediatamente.
- thinking actualiza la fase.
- delta se concatena una sola vez.
- end consolida respuesta y fuentes.
- cancelación no genera toast de error genérico.
- timeout permite reintentar.
- desconexión no duplica respuesta.
- permisos 401 y 403 redirigen o informan sin bucle de refresh.

### Verificación

       docker compose exec -T frontend npm test
       docker compose exec -T frontend npm run build
       docker compose exec -T frontend npm run lint

Si el contenedor no incluye dependencias de desarrollo, ejecutar los mismos scripts desde frontend con el runtime configurado y documentarlo.

### Criterio de cierre

La UI muestra progreso en menos de 300 ms p95 en entorno caliente, puede cancelar y no introduce refrescos continuos.

### Commit sugerido

feat(chat-ui): expose AI progress and cancellation

---

## FASE 7 — Seguridad, regresión, concurrencia y pruebas negativas

### Objetivo

Demostrar que las optimizaciones no saltan permisos ni vuelven inestable el pipeline.

### 7.1 Matriz de permisos

Probar como mínimo:

| Actor | Alcance | Resultado esperado |
|---|---|---|
| Administrador autorizado | Tenant completo | Accede a documentos del tenant |
| Gestor limitado | Proyecto o subconjunto | Sólo fuentes de su alcance |
| Auditor de lectura | Alcance de lectura | Responde y cita sin mutar |
| Usuario sin proyecto | Vacío | No recupera ni reutiliza caché |
| Usuario de otro tenant | Otro tenant | 404 o 403 según contrato, nunca datos |

Repetir para:

- búsqueda exacta;
- búsqueda estructurada;
- búsqueda híbrida;
- resolución de referencias;
- caché exacta;
- caché semántica;
- documentos relacionados;
- historial conversacional;
- endpoint streaming;
- endpoint no streaming.

### 7.2 Casos de seguridad

- Prompt injection dentro de OCR.
- Documento que pide revelar system prompt.
- Nombre de archivo malicioso.
- HTML o Markdown hostil en fragmentos.
- Cita a bloque borrado.
- Caché generada antes de revocar permiso.
- Cambio de tenant con la misma sesión.
- Consulta semánticamente similar entre usuarios con alcances distintos.

### 7.3 Concurrencia y resiliencia

- Varias consultas simultáneas y extracción en background.
- Saturación controlada de GPU.
- Reinicio de worker durante HyperExtract.
- Reinicio de backend durante stream.
- Timeout del proveedor.
- Redis temporalmente no disponible.
- Reranker no disponible.
- Cancelación masiva.
- Reejecución de backfill.

### 7.4 Suite mínima

Ejecutar al menos:

       docker compose exec -T backend pytest backend/tests/test_classification.py -q
       docker compose exec -T backend pytest backend/tests/test_ai_agent_refactor.py -q
       docker compose exec -T backend pytest backend/tests/test_ai_chat_real.py -q
       docker compose exec -T backend pytest backend/tests/test_ai_stream_context.py -q
       docker compose exec -T backend pytest backend/tests/test_ai_ocr_confidence_prompt.py -q
       docker compose exec -T backend pytest backend/tests/test_ai_token_budget.py -q
       docker compose exec -T backend pytest backend/tests/test_chat_context_size_retry.py -q
       docker compose exec -T backend pytest backend/tests/test_prompt_injection.py -q
       docker compose exec -T backend pytest backend/tests/test_search_scope_contract.py -q
       docker compose exec -T backend pytest backend/tests/test_tenant_access.py -q

Adaptar la ruta a tests si dentro del contenedor el cwd ya es backend. No omitir una suite por ese detalle.

Además:

- ejecutar todas las pruebas nuevas;
- ejecutar la suite backend completa;
- ejecutar frontend test, build y lint;
- ejecutar migraciones desde una base vacía;
- ejecutar upgrade sobre copia de base con datos;
- ejecutar pruebas negativas de permisos;
- ejecutar benchmark bajo concurrencia.

### Criterio de cierre

Cero fuga de datos, cero regresión crítica, cero trabajo duplicado y suite completa verde. Cualquier test omitido debe documentarse como bloqueo real; no puede ocultarse.

### Commits sugeridos

1. test(security): cover scoped AI cache and retrieval
2. test(pipeline): verify idempotency under retries
3. test(performance): certify concurrent AI workloads

---

## FASE 8 — Certificación final, rollout y cierre

### Objetivo

Comparar antes/después sobre datos reales y dejar la aplicación operable.

### Tareas

#### 8.1 Ejecución final sobre corpus

- Restaurar o usar una copia aislada de la línea base.
- Procesar los 27 documentos únicos.
- No borrar ni alterar el corpus original.
- Registrar duplicados, fallos y revisiones.
- Esperar a que todas las colas queden en estado terminal.
- Confirmar:
  - text_ready;
  - search_ready;
  - enriched o razón explícita de no enriquecido;
  - clasificación revisada;
  - no needs_reembedding;
  - no pendientes huérfanos.

#### 8.2 Comparación

Publicar en docs/MINIMAX_M3_RESULTADOS_FINALES.md:

- hardware y configuración;
- commits incluidos;
- línea base y resultado;
- p50, p95 y máximo;
- frío y caliente;
- TTFE y TTFT;
- hit rate de caché;
- tokens;
- precisión de extracción;
- matriz de clasificación;
- exactitud y citas del chat;
- fallos y su causa;
- pruebas de permisos;
- riesgos residuales;
- instrucciones de rollback.

No afirmar una mejora si las muestras o condiciones no son comparables.

#### 8.3 Configuración

- Añadir nuevas variables a .env.example con defaults seguros.
- Documentar perfiles de modelo, límites y colas.
- Mantener flags de rollout para:
  - nueva caché;
  - routing;
  - prompt v2;
  - clasificación v2;
  - enriquecimiento asíncrono.
- El default de producción debe activarse sólo tras certificación.

#### 8.4 Observabilidad y rollback

- Dashboard o consulta documentada para latencia, errores, colas y cache hit.
- Alertas por p95, JSON inválido, timeouts, backlog y fugas de alcance detectadas.
- Procedimiento para desactivar prompt, routing o caché sin perder datos.
- Migración reversible.

#### 8.5 Auditoría final de Git

       git status --short
       git diff --check
       git log --oneline --decorate -30

- Confirmar que cada commit contiene sólo su tarea.
- Confirmar que no se versionó ningún documento real ni secreto.
- Confirmar que los cambios locales previos continúan intactos.

### Criterio de cierre global

El plan sólo está terminado cuando:

- todos los criterios de la sección 7 se cumplen o existe una desviación aprobada y documentada;
- el corpus real ha sido certificado;
- las pruebas negativas de permisos pasan;
- las colas están limpias o cada excepción tiene causa;
- frontend y backend están verificados;
- existe informe antes/después;
- existe rollback;
- no quedan tareas del plan marcadas sólo como “compila”.

### Commit sugerido

docs(certification): record MiniMax M3 performance and quality results

---

## 9. Matriz obligatoria de evaluación

| Caso | Clasificación | Extracción | Recuperación | Respuesta | Seguridad |
|---|---|---|---|---|---|
| MSG con pedido | email + pedido | remitente, fecha, intención | exacta y estructurada | hecho y cita | alcance |
| XLSX de carpintería | spreadsheet + medición/coste | hojas y campos | estructurada | síntesis breve | alcance |
| JPEG de presupuesto firmado | image + presupuesto + firmado | partes, fecha, estado | OCR/VLM | respuesta con aviso sólo si OCR bajo | alcance |
| PDF de incidencia | pdf + incidencia | problema y acciones | híbrida selectiva | no confundir con foto | alcance |
| DOCX de medición | word + medición | elementos y cantidades | exacta/estructurada | respuesta citada | alcance |
| Documento con identificador | tipo correcto | identificador | exacta primero | <= objetivo factual | alcance |
| Dos documentos contradictorios | tipos correctos | fechas y valores | multifuente | expone conflicto | alcance |
| Sin evidencia | no aplica | no aplica | sin falsos positivos | abstiene | no fuga |
| OCR bajo | tipo probable + review | campos con confianza | ventana local | cautela localizada | alcance |
| Prompt injection | tipo correcto | texto no ejecutable | contexto seguro | ignora instrucción | no fuga |
| Caché repetida | no aplica | no aplica | cache hit | misma calidad < 1 s | aislamiento |
| Permiso revocado | no aplica | no aplica | cache miss o bloqueo | no responde con dato antiguo | aislamiento |

---

## 10. Decisiones que deben apoyarse en datos

MiniMax M3 no puede elegir por intuición:

- modelo rápido frente a modelo capaz;
- reranker siempre frente a selectivo;
- dos variantes frente a tres;
- tamaño de contexto;
- max_tokens;
- texto frente a VLM;
- extracción síncrona frente a asíncrona;
- caché exacta frente a semántica;
- umbrales de baja confianza.

Para cada decisión:

1. Definir hipótesis.
2. Medir línea base.
3. Cambiar una variable principal.
4. Ejecutar el mismo conjunto.
5. Comparar precisión, citas, latencia, tokens y memoria.
6. Conservar evidencia.
7. Elegir la opción que cumple calidad y seguridad con menor coste.

---

## 11. Formato de progreso de MiniMax M3

Después de cada tarea debe registrar:

- tarea realizada;
- archivos modificados;
- prueba ejecutada;
- resultado exacto;
- métrica antes/después si aplica;
- commit;
- riesgo o pendiente.

Formato:

    [FASE X.Y]
    Cambio:
    Evidencia:
    Pruebas:
    Métricas:
    Commit:
    Pendiente:

No usar “funciona”, “listo” o “mejorado” sin evidencia.

---

## 12. Lista final de comprobación

### Línea base

- [ ] Benchmark API autenticado reproducible.
- [ ] Medición fría y caliente.
- [ ] TTFE, TTFT y tiempo total.
- [ ] Muestra de extracción estratificada.
- [ ] Conjunto dorado versionado y anonimizado.

### Clasificación

- [ ] 27 documentos revisados.
- [ ] 12 o más revisados en profundidad.
- [ ] source_format separado de document_type.
- [ ] Evidencia y versión persistidas.
- [ ] Endpoint de reclasificación persiste confidence.
- [ ] Aprendizaje existente reutilizado.
- [ ] Backfill dry-run e idempotente.
- [ ] Matriz antes/después.

### Extracción

- [ ] text_ready no espera HyperExtract.
- [ ] Huella evita repeticiones.
- [ ] Cliente HTTP reutilizado.
- [ ] max_tokens por perfil.
- [ ] JSON schema cuando sea compatible.
- [ ] Reparación acotada.
- [ ] Routing texto/VLM medido.
- [ ] Colas interactivas priorizadas.

### Chat

- [ ] Caché leída antes de retrieval.
- [ ] Caché aislada e invalidada.
- [ ] start SSE <= 300 ms p95.
- [ ] Exacto antes de híbrido.
- [ ] Multi-query selectivo.
- [ ] Reranker selectivo y caliente.
- [ ] Routing de modelo medido.
- [ ] Cancelación extremo a extremo.

### Prompt y contexto

- [ ] Prompts versionados.
- [ ] Contexto priorizado por evidencia.
- [ ] Hechos, inferencias y conflictos diferenciados.
- [ ] Citas por hecho.
- [ ] Abstención comprobada.
- [ ] Inyección documental neutralizada.
- [ ] Evaluación determinista A/B.

### Seguridad y cierre

- [ ] Pruebas negativas de permisos.
- [ ] Sin fugas de caché.
- [ ] Migración vacía y con datos.
- [ ] Suite backend completa.
- [ ] Frontend test, build y lint.
- [ ] Prueba de concurrencia y reinicio.
- [ ] Corpus certificado.
- [ ] Informe final antes/después.
- [ ] Rollback documentado.
- [ ] Commits pequeños.
- [ ] Cambios locales previos conservados.

---

## 13. Prompt de lanzamiento para MiniMax M3

> Trabaja en C:\Users\Usuario\Desktop\OCR\OCR\docu-intel. Lee íntegramente PLAN_MINIMAX_M3_RENDIMIENTO_EXTRACCION_CLASIFICACION_CONTEXTO_IA.md y AGENTS.md antes de modificar código. Implementa todas las fases en orden y de forma continua, sin esperar mensajes de “continúa”. Conserva todos los cambios locales existentes, no uses operaciones destructivas de Git y realiza commits pequeños por tarea sólo después de verificarlos. Usa D:\TEST2025\2025\BON PLA SOCIEDAD ANONIMA como corpus real autorizado, sin copiar documentos ni datos sensibles al repositorio. No declares una fase terminada por compilar: ejecuta benchmarks reproducibles, pruebas funcionales, pruebas negativas de permisos, migraciones, frontend, backend y todos los criterios de aceptación. Informa el progreso con métricas, pruebas y hashes de commit. Detente únicamente ante un bloqueo real que requiera autorización o implique riesgo de datos.

---

## 14. Definición de terminado

MiniMax M3 habrá terminado cuando pueda demostrar, con resultados reproducibles:

1. Por qué se clasificaba mal cada familia problemática.
2. Que la nueva clasificación representa formato y significado sin mezclarlos.
3. Que el documento es buscable antes del enriquecimiento caro.
4. Que la extracción es más rápida, estable e idempotente.
5. Que el chat empieza a responder inmediatamente y termina dentro de los objetivos.
6. Que los prompts y el paquete de contexto mejoran hechos, citas y abstención.
7. Que la caché y la recuperación nunca cruzan permisos.
8. Que el corpus real completa el ciclo sin pendientes inexplicados.
9. Que todas las pruebas y criterios están documentados.
10. Que el repositorio conserva intactos los cambios locales ajenos.

Hasta entonces, el plan sigue abierto.
