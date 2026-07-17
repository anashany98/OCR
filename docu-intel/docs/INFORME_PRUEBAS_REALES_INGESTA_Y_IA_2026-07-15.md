# Informe de pruebas reales: ingesta y preguntas a IA

**Fecha:** 15 de julio de 2026  
**Entorno:** Docker local de Docu-Intel  
**Alcance:** validacion de punta a punta con archivos reales: carga, extraccion, OCR/parsing, fragmentacion, embeddings, busqueda y respuesta de IA con fuentes.

## Resultado ejecutivo

La ingesta de los seis formatos termino sin errores fatales. Los cinco archivos nuevos generaron trabajos de extraccion correctos y, tras recuperar la fase de embeddings, los seis documentos quedaron disponibles para busqueda lexica y semantica.

- Cuatro de las seis preguntas iniciales citaron el documento objetivo.
- Excel fue la unica pregunta que recupero de forma explicita la senal esperada: la referencia `252234`.
- La imagen no recupero su propio documento y respondio con un fallback fundamentado sobre documentos no pertinentes. El control evito una afirmacion sin evidencia, pero la recuperacion fue incorrecta.
- El DWG respondio de forma segura sin contexto al preguntar por el nombre del archivo. Una segunda pregunta basada en los datos extraidos si recupero las cotas `0.73`, `0.71` y unidades `mm`.

Hay una incidencia tecnica confirmada: la cola asincrona de embeddings no se encolo porque la comprobacion de conexion Celery devuelve un objeto de contexto en lugar de la conexion. Redis y Celery estaban disponibles. El re-embebido administrativo recupero correctamente los documentos, pero esta ruta no debe ser necesaria en operacion normal.

## Muestra utilizada

Los archivos se tomaron de `D:\TEST2025\2025`. Para no repetir datos de clientes, la tabla usa solo el nombre del archivo, formato e identificador interno.

| Formato | Archivo real | Documento | Resultado de ingesta |
|---|---|---:|---|
| MSG | `RE_ PRESUPUESTO colchon + canape abatible (Particular).msg` | 161579 | Procesado; 2 paginas; 3 bloques iniciales; confianza OCR 0,98 |
| XLSX | `252234.xlsx` | 161580 | Procesado; 3 paginas; 3 bloques; confianza 0,50 |
| PDF | `CONFIRMACION PEDIDO DUPEN.pdf` | 161581 | Procesado; 1 pagina; 1 bloque; 3 entidades; confianza 0,60 |
| JPEG | `incidencia canape (1).jpeg` | 161582 | Extraido correctamente; queda en `needs_review`; 1 pagina; confianza OCR 0,98 |
| DOCX | `IBEROSTAR GRAND BAVARO.docx` | 161583 | Procesado; 4 paginas; 7 bloques; confianza OCR 0,98 |
| DWG | `logo bluesea medidas para mostrador recepcion.dwg` | 161483 | Reutilizacion por deduplicacion de un documento ya existente; procesado y buscable |

La API acepto los seis archivos (`uploaded=6`, `duplicates=0`, `failed=0`). El DWG no abrio un nuevo trabajo porque el contenido ya estaba registrado y se reutilizo el documento 161483. Esto verifica tambien la deduplicacion.

## Rendimiento de extraccion

| Documento | Trabajo | Duracion | Reintentos | Estado |
|---:|---|---:|---:|---|
| 161579 (MSG) | `extract` | 11,98 s | 0 | Procesado |
| 161580 (XLSX) | `extract` | 0,47 s | 0 | Procesado |
| 161581 (PDF) | `extract` | 0,81 s | 0 | Procesado |
| 161582 (JPEG) | `extract` | 9,67 s | 0 | Procesado |
| 161583 (DOCX) | `extract` | 16,48 s | 0 | Procesado |

No se observaron errores de extraccion. Los tiempos mas altos corresponden a MSG, JPEG y DOCX, que activan parsing y/o OCR mas intensivo.

## Embeddings y disponibilidad de busqueda

Inmediatamente despues de la extraccion, los cinco documentos nuevos tenian 47 fragmentos creados, pero cero embeddings y el estado `embedding_pending`. El log del worker indico para cada documento que los embeddings serian recogidos posteriormente por el barrido de re-embebido.

La causa quedo reproducida:

1. Redis respondio `PONG` y una conexion directa de Celery con `connection_for_write()` fue satisfactoria.
2. La funcion interna `_celery_broker_available()` devolvio `False`.
3. `connection_or_acquire()` devuelve un `FallbackContext`; el codigo intenta ejecutar `ensure_connection()` sobre ese envoltorio, por lo que la comprobacion falla aunque el broker esta disponible.

Se ejecuto la operacion administrativa normal `POST /api/v1/admin/documents/{id}/re-embed` para los cinco documentos nuevos. El proveedor `local_openai_compatible` genero los vectores sin errores. Estado final comprobado en base de datos:

| Documento | Fragmentos finales | Con embedding | Estado de pipeline | Lexica | Semantica |
|---:|---:|---:|---|---|---|
| 161483 (DWG) | 1 | 1 | `searchable` | Si | Si |
| 161579 (MSG) | 33 | 33 | `searchable` | Si | Si |
| 161580 (XLSX) | 3 | 3 | `searchable` | Si | Si |
| 161581 (PDF) | 3 | 3 | `searchable` | Si | Si |
| 161582 (JPEG) | 4 | 4 | `searchable` | Si | Si |
| 161583 (DOCX) | 14 | 14 | `searchable` | Si | Si |

Observacion: el MSG paso de 23 a 33 fragmentos despues del re-embebido. Conviene anadir una prueba de idempotencia de fragmentacion, porque esa ruta afirma reconstruir los mismos fragmentos a partir de `DocumentPage.text`.

## Pruebas reales de preguntas a IA

Las consultas se enviaron a `POST /api/v1/ai/ask` con sesiones nuevas, evitando respuestas previas de cache. Se valido que la respuesta no estuviera vacia, que citase el documento objetivo y que incluyera senales factuales esperadas. Las respuestas no se reproducen para no volcar contenidos de documentos reales en este informe.

| Caso | Pregunta controlada | Respuesta | Fuente objetivo | Senal factual esperada | Resultado |
|---|---|---|---|---|---|
| MSG | Numero de presupuesto mencionado en el correo | Si; `qwen3-8b`; confianza 0,555 | Si, 161579 | No detectada | Parcial |
| XLSX | Referencia o presupuesto de `252234.xlsx` | Si; `qwen3-8b`; confianza 0,667 | Si, 161580 | `252234` encontrada | Correcto |
| PDF | Tipo y paginas de la confirmacion de pedido | Si; `qwen3-8b`; confianza 0,555 | Si, 161581 | No detectada | Parcial |
| JPEG | Resumen de la incidencia de la imagen | Si; fallback fundamentado | No; recupero 10 documentos ajenos | No | Fallo de recuperacion, respuesta segura |
| DOCX | Identificacion del documento tecnico | Si; `qwen3-8b`; confianza 0,555 | Si, 161583 | No detectada | Parcial |
| DWG (por nombre) | Elementos o medidas del plano identificado por nombre | Si; fallback sin contexto | No | No | Fallo de resolucion por nombre |

La respuesta de la imagen tuvo `fallback_reason=validation_source_coverage`: el sistema detecto que no podia respaldar la respuesta con la fuente adecuada. Es un buen comportamiento de seguridad, pero no sustituye recuperar el documento correcto.

### Contraprueba CAD/DWG

Se hizo una pregunta basada en el contenido extraido, no en el nombre del fichero: "Que cotas y unidades se han detectado?".

- Respuesta no vacia con `qwen3-8b` y confianza 0,617.
- Cito el DWG 161483 y un documento CAD relacionado.
- Recupero las tres senales esperadas: `0.73`, `0.71` y `mm`.

Conclusion: el parser DWG y su indexacion contienen informacion utilizable. El deficit esta en resolver un archivo por `original_filename`/`source_path` y anadir esos metadatos al contexto de chat.

## Hallazgos y acciones recomendadas

### Prioridad alta

1. **Corregir el encolado automatico de embeddings.** Sustituir la comprobacion basada en `connection_or_acquire()` por una conexion real de Celery y anadir una prueba de integracion que verifique que un documento recien ingerido recibe la tarea `embed_document_task` cuando Redis esta disponible. Criterio: no debe quedar ningun documento nuevo en `embedding_pending` por este motivo.
2. **Incorporar nombre original y ruta de origen a la recuperacion de chat.** La busqueda exacta actual busca entidades y referencias, no nombres de archivo. Crear una etapa de resolucion por `original_filename` y `source_path`, previa a la recuperacion semantica. Criterio: preguntas que contienen un nombre de archivo deben citar ese documento.
3. **Corregir la recuperacion de imagenes de incidencia.** Indexar de forma explicita el nombre y el tipo documental como senales de recuperacion, y probar que una pregunta sobre `incidencia canape (1).jpeg` no devuelva fuentes ajenas.

### Prioridad media

4. **Prueba de idempotencia del re-embebido.** Comparar conjunto y numero de fragmentos antes y despues de `reembed_document`; el MSG genero 10 fragmentos adicionales durante la recuperacion.
5. **Evaluar calidad factual por tipo de archivo.** Anadir un corpus QA sin datos sensibles: pregunta, fuente esperada, respuesta esperada y minimo de citas. Las cuatro respuestas parciales citaron bien, pero no devolvieron la senal factual definida en esta ejecucion.
6. **Mostrar estado `needs_review` de la imagen en la UI de chat.** La imagen fue indexada y buscable, pero mantiene revision pendiente; la interfaz deberia indicarlo al usarla como fuente.

## Veredicto

La plataforma ya procesa archivos reales heterogeneos y puede responder con citas verificables. No esta todavia lista para considerar fiable la consulta por nombre de archivo ni la consulta sobre imagenes de incidencias: ambas necesitan las correcciones anteriores. La recuperacion de embeddings tambien requiere arreglo antes de una ingesta masiva, porque ahora necesita una intervencion administrativa manual pese a que la infraestructura de cola esta disponible.
