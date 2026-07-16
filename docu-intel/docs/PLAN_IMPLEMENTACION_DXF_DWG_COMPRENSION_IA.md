# Plan de implementación: comprensión real de DXF/DWG por la IA

Estado: listo para implementación

Fecha de auditoría: 2026-07-15

Repositorio: Docu-Intel

Documento padre: docs/BRIEF_MIMO_COMPRENSION_PLANOS_Y_MEMORIAS_OBRA.md

## 1. Objetivo

Convertir los DXF y DWG en conocimiento técnico estructurado, visualizable y consultable por chat, conservando siempre:

- Entidad CAD original.
- Capa y layout.
- Coordenadas CAD.
- Valor y unidad originales.
- Conversión normalizada, cuando sea verificable.
- Documento, hoja y revisión.
- Método de extracción.
- Confianza y estado de validación.

El resultado no debe limitarse a una lista de textos y cotas. La IA debe poder responder preguntas como:

- ¿Qué elementos M1-M6 aparecen en este plano?
- ¿Qué cotas tiene M3?
- ¿Cuál es la dimensión impresa y en qué unidad?
- ¿Qué capas contiene el dibujo?
- ¿Dónde se encuentra este elemento?
- ¿Qué cambia entre dos revisiones?
- ¿La cota impresa coincide con la geometría?

## 2. Alcance

Incluido:

- DXF nativo.
- DWG convertido de forma controlada a DXF.
- Texto, cotas, geometría, bloques, capas, layouts y extents.
- Persistencia estructurada.
- Preview CAD y overlays.
- Embeddings y búsqueda híbrida.
- Herramientas de chat específicas.
- Reprocesado seguro de documentos existentes.
- Corrección del preview pequeño para imágenes raster.
- Métricas, fixtures, benchmark y certificación Docker.

Fuera de este plan:

- Edición CAD completa.
- Reconstrucción 3D.
- Soporte RVT nativo.
- Cómputos contractuales sin confirmación humana.
- Inferir habitaciones donde el documento no representa espacios arquitectónicos.

## 3. Reglas innegociables

1. La geometría CAD es la fuente principal. OCR y VLM son respaldo o validación.
2. No usar el bbox del texto de una cota como longitud física.
3. No asumir metros ni milímetros cuando la unidad no sea verificable.
4. Conservar valor y unidad originales antes de normalizar.
5. No borrar correcciones manuales confirmadas durante un reprocesado.
6. Toda respuesta técnica debe citar documento y evidencia.
7. Una discrepancia se marca para revisión; no se corrige silenciosamente.
8. El sistema debe seguir funcionando con la nueva extracción desactivada.
9. No introducir archivos privados del corpus del usuario en Git.
10. No ejecutar borrados masivos ni tests sobre la base real.

## 4. Evidencia de partida

### 4.1 Prueba real: documento 161483

Archivo: logo bluesea medidas para mostrador recepcion.dwg

Resultado actual:

- Estado processed.
- Tipo clasificado como medicion.
- Conversión DWG a DXF correcta.
- Motor dxf_parser.
- Texto y búsqueda semántica disponibles.
- 1 chunk y 1 embedding.
- 2 bloques de texto.
- Cotas detectadas en el texto: 0.73 y 0.71.
- Resumen CAD: 4 líneas y 2 entidades DIMENSION.
- 0 PlanDimension persistidas.
- 0 PlanRoom persistidas.
- Preview HTTP 200 de 1400 x 1000.

### 4.2 Prueba real: documento 161484

Archivo: 2025-02-10-mobles habitació 6110.dwg

Resultado actual:

- Estado processed.
- Tipo plano.
- Conversión DWG a DXF correcta.
- Motor dxf_parser.
- 235 bloques de texto.
- 4 chunks y 4 embeddings.
- Detectados MOBLES A MIDA, M1-M6, plantas, alzados y secciones.
- Muchas cotas están presentes en el texto.
- 0 PlanDimension persistidas.
- 0 PlanRoom persistidas.
- Preview HTTP 200 de 1400 x 1000.

Que este documento no genere habitaciones puede ser correcto: es un plano de mobiliario. Debe generar elementos, cotas, vistas y relaciones, no inventar estancias.

### 4.3 Problemas confirmados

P0 crítico:

- El parser conserva cotas y geometría solo en variables locales y las aplana a texto.
- persist_plan_extraction recibe texto, no el resultado CAD tipado.
- PlanDimension no recibe las entidades DIMENSION del DXF.
- El reprocesado elimina Plan y sus hijos antes de regenerarlos; esto puede destruir confirmaciones manuales.

P1 alto:

- Existen dos parsers DXF con capacidades solapadas.
- La unidad de DIMENSION aparece codificada como mm en una ruta, mientras la persistencia textual puede inferir m.
- PlanDimension no conserva capa, handle, extremos, fuente de unidad ni estado de validación.
- Los bloques INSERT no se convierten sistemáticamente en elementos consultables.
- El chat solo dispone de una herramienta centrada en medidas por nombre de habitación.
- La frase “qué medidas aparecen” puede producir una habitación falsa llamada “aparecen”.

P2 medio:

- El preview CAD funciona, pero se genera bajo demanda y puede reconvertir un DWG.
- DocumentPage no conserva una imagen CAD y una transformación CAD-a-preview útil para overlays.
- Las imágenes raster directas siguen usando una miniatura de 200 x 280 en el visor.
- El encolado inicial de embeddings informa broker unavailable aunque el barrido posterior completa los embeddings.
- Falta un SLO observable para el tiempo text_ready a semantic_search_ready.

## 5. Arquitectura objetivo

Flujo:

    DWG original
      -> puente ODA autenticado
      -> DXF temporal
      -> parser CAD canónico
      -> resultado CAD tipado
          -> página/texto buscable
          -> entidades CAD persistidas
          -> PlanDimension / PlanRoom / PlanSymbol
          -> preview y transformación de coordenadas
          -> chunks técnicos y embeddings
          -> herramientas deterministas de chat

Para DXF se omite únicamente la conversión ODA.

Prioridad de fuentes:

    entidad CAD confirmada
      -> geometría CAD calculada
      -> dato manual confirmado
      -> texto CAD
      -> OCR/Ovis del render
      -> sugerencia VLM

El dato manual confirmado no se reemplaza automáticamente. Si entra en conflicto con una nueva extracción, se crea una discrepancia revisable.

## 6. Contrato de extracción CAD

### 6.1 Tipos nuevos

Añadir en backend/app/parsers/types.py contratos tipados compatibles con ExtractedDocument:

- CadExtraction.
- CadMetadata.
- CadTextEntity.
- CadDimensionEntity.
- CadGeometryEntity.
- CadInsertEntity.
- CadRenderTransform.

ExtractedDocument recibe un campo opcional cad con valor por defecto None. No se modifica la interfaz pública de OCR ni embeddings.

Campos mínimos:

CadMetadata:

- source_format: dxf o dwg.
- dxf_version.
- converter_name y converter_version, si aplica.
- modelspace/layout.
- insunits_code e insunits_name.
- extents.
- layers.
- coordinate_system.
- source_hash y converted_hash.

CadDimensionEntity:

- entity_handle.
- layer y layout.
- dimension_type.
- raw_measurement.
- displayed_text.
- text_override.
- native_unit.
- unit_source.
- dimlfac.
- normalized_value_m.
- definition_points.
- dimension_line_point.
- text_midpoint.
- confidence.
- validation_status.

CadGeometryEntity:

- entity_handle.
- entity_type.
- layer y layout.
- geometry_json.
- closed.
- bbox/extents.

CadInsertEntity:

- entity_handle.
- block_name.
- layer y layout.
- insertion_point.
- rotation.
- scale.
- attributes.

CadRenderTransform:

- cad_min_x, cad_min_y, cad_max_x, cad_max_y.
- preview_width y preview_height.
- scale_x y scale_y.
- offset_x y offset_y.
- invert_y.

### 6.2 Resolución de unidades

Orden de decisión:

1. Texto/override explícito de la cota.
2. Estilo DIMENSION: DIMLUNIT, DIMLFAC y demás propiedades aplicables.
3. Cabecera $INSUNITS.
4. Unidad de proyecto confirmada manualmente.
5. unknown.

Requisitos:

- Guardar siempre raw_measurement.
- Guardar unit_source.
- Normalizar a metros solo cuando exista unidad verificable.
- Si hay contradicción entre cabecera, estilo y texto, conservar todas las señales y marcar needs_review.
- Nunca aplicar un default silencioso de metros o milímetros.

## 7. Fases de implementación

## FASE CAD0 - Puerta de seguridad y corpus

Objetivo: poder medir cambios sin depender de la base viva.

Tareas:

1. Crear fixtures DXF sintéticos/anónimos:
   - Una habitación rectangular cerrada.
   - TEXT y MTEXT.
   - Dos DIMENSION con unidad mm.
   - Una DIMENSION con override en m.
   - INSERT de puerta, ventana y M1.
   - Varias capas.
   - Modelspace y un layout.
   - Un DXF sin texto pero con geometría.
2. Crear manifest esperado por fixture.
3. Añadir un fixture DWG opcional para integración local; no debe bloquear CI sin puente ODA.
4. Crear scripts/benchmark_cad_ingestion.py.
5. Registrar baseline sin hardcodear IDs de base en tests.

Archivos:

- backend/tests/fixtures/cad/
- backend/tests/test_cad_golden.py
- scripts/benchmark_cad_ingestion.py

Aceptación:

- Fixtures no contienen datos privados.
- El benchmark produce JSON reproducible.
- Se conocen conteos esperados de textos, cotas, capas, inserts y geometrías.
- Los tests se niegan a usar una base no marcada como test.

Commit recomendado: CAD0-corpus-and-safety

## FASE CAD1 - Parser canónico y contrato tipado

Objetivo: impedir que la información CAD se pierda al convertirla en texto.

Tareas:

1. Convertir backend/app/parsers/dxf.py en parser canónico.
2. Reutilizar el render y capacidades útiles de backend/app/services/dxf_parser.py.
3. Mantener temporalmente services/dxf_parser.py como shim compatible y retirarlo cuando no tenga consumidores.
4. Extraer:
   - TEXT y MTEXT.
   - DIMENSION.
   - LINE.
   - LWPOLYLINE y POLYLINE.
   - ARC y CIRCLE.
   - SPLINE cuando pueda representarse de forma segura.
   - INSERT y atributos.
   - Capas.
   - Modelspace/layouts.
   - Extents.
5. No devolver documento vacío si existe geometría aunque no haya texto.
6. Adjuntar CadExtraction a ExtractedDocument.
7. Hacer que parse_dwg conserve procedencia de la conversión antes de eliminar el DXF temporal.

Archivos:

- backend/app/parsers/types.py
- backend/app/parsers/dxf.py
- backend/app/parsers/dwg.py
- backend/app/services/dxf_parser.py
- backend/app/parsers/router.py
- backend/tests/test_dxf_structured_parser.py
- backend/tests/test_dwg_parser.py

Aceptación:

- El DXF sintético devuelve entidades tipadas, no solo texto.
- Cada entidad conserva handle, capa y coordenadas.
- Unidades no verificables quedan como unknown.
- DWG y DXF producen el mismo contrato después de la conversión.
- El original DWG nunca se modifica.
- Los tests actuales de DWG siguen verdes.

Commit recomendado: CAD1-typed-parser

## FASE CAD2 - Modelo de datos y persistencia

Objetivo: convertir entidades CAD en hechos técnicos consultables.

### Migración

Crear una migración Alembic nueva. No editar migraciones históricas.

Extender plans:

- source_format.
- cad_unit.
- cad_extents_json.
- coordinate_transform_json.
- conversion_provenance_json.

Extender plan_dimensions:

- source_method.
- source_entity_handle.
- layer.
- native_value.
- native_unit.
- unit_source.
- normalized_value_m, reutilizando value_m si se mantiene compatibilidad.
- start_point_json.
- end_point_json.
- label_point_json.
- validation_status.
- needs_review.

Crear plan_cad_entities:

- id.
- plan_id.
- entity_handle.
- entity_type.
- layer.
- layout.
- geometry_json.
- properties_json.
- source_method.
- confidence.
- validation_status.

Índice/constraint recomendado:

- Único por plan_id + entity_handle + source_method.
- Índices por plan_id, entity_type, layer y validation_status.

No usar handle como identificador global entre revisiones.

### Persistencia

1. Pasar CadExtraction desde el parseo hasta la fase técnica.
2. Añadir persist_cad_extraction o ampliar persist_plan_extraction con parámetro cad opcional.
3. Persistir primero la fuente CAD.
4. Ejecutar extracción regex/OCR como complemento.
5. Deduplicar hechos por procedencia, coordenadas y valor.
6. Convertir DIMENSION a PlanDimension.
7. Convertir INSERT reconocido a PlanSymbol o elemento técnico.
8. Conservar INSERT desconocido en plan_cad_entities.
9. Convertir polilíneas cerradas en candidatos PlanRoom únicamente si pasan validaciones geométricas.
10. Asociar labels a polígonos mediante punto-en-polígono y proximidad.

### Reprocesado seguro

Eliminar el patrón destructivo de borrar Plan completo antes de cada extracción.

Reglas:

- Upsert de resultados automáticos por source_entity_handle.
- Borrar solo filas automáticas obsoletas de la misma versión de extracción.
- Preservar filas manuales o confirmed.
- Si una extracción nueva contradice una confirmación, crear conflicto y needs_review.
- Guardar parser_version/extraction_fingerprint para idempotencia.

Archivos:

- backend/app/models/business.py
- backend/app/schemas/business.py
- backend/app/services/document_processing_core.py
- backend/app/services/plan_extraction.py
- backend/app/services/technical_pipeline.py
- backend/app/api/routes/plans.py
- backend/alembic/versions/
- backend/tests/test_cad_persistence.py
- backend/tests/test_cad_reprocess_idempotency.py
- backend/tests/test_cad_manual_preservation.py

Aceptación:

- Documento 161483 genera dos PlanDimension o quedan explícitamente en revisión por unidad ambigua.
- Documento 161484 persiste cotas y M1-M6 sin inventar habitaciones.
- Reprocesar dos veces no duplica datos.
- Una cota manual confirmada sobrevive al reprocesado.
- Rollback de la migración está probado en base de test.

Commit recomendado: CAD2-structured-persistence

## FASE CAD3 - Preview, coordenadas y overlays

Objetivo: que el usuario vea la evidencia exacta citada por la IA.

Estado confirmado:

- El endpoint CAD ya devuelve previews de 1400 x 1000 para ambos DWG.
- No es necesario sustituirlo.

Mejoras:

1. Renderizar el preview durante la ingesta usando el DXF ya convertido.
2. Evitar una segunda conversión DWG cuando el usuario abre el visor.
3. Guardar el preview o page image y CadRenderTransform.
4. Permitir transformar coordenadas CAD a píxeles del preview.
5. Dibujar overlays de:
   - Cotas y extremos.
   - Elementos M1-M6.
   - Bloques.
   - Polígonos de estancias.
   - Fuente citada por el chat.
6. Permitir seleccionar una región y enviarla al chat como contexto activo.
7. Mantener miniaturas pequeñas para listas.
8. Para imágenes raster abiertas en el visor, crear preview independiente de alta resolución y no ampliar la miniatura 200 x 280.

Archivos:

- backend/app/services/thumbnail.py
- backend/app/api/routes/thumbnails.py
- backend/app/services/document_processing_core.py
- backend/app/api/routes/plans.py
- frontend/src/pages/document/DocumentDetailPage.tsx
- frontend/src/pages/plano/
- frontend/src/api/client.ts
- frontend/src/types/api.ts
- backend/tests/test_cad_preview.py
- frontend tests del visor

Aceptación:

- Preview CAD devuelve HTTP 200 y al menos 1400 x 1000.
- Abrir un DWG ya procesado no vuelve a llamar al puente ODA.
- El overlay de una cota cae sobre la entidad correcta con tolerancia de 2 píxeles.
- Una imagen raster usa preview de visor, no la miniatura.
- Seleccionar M3 y preguntar “¿qué mide esto?” adjunta documento y coordenadas.

Commit recomendado: CAD3-preview-and-overlays

## FASE CAD4 - Embeddings y búsqueda

Objetivo: hacer buscable el contenido técnico sin perder exactitud.

Estado confirmado:

- worker-fast ya consume text_fast, embeddings y celery.
- Los documentos 161483 y 161484 terminaron semantic_search_ready.
- El problema es latencia/observabilidad del encolado, no ausencia de worker.

Tareas:

1. Investigar por qué _celery_broker_available informa unavailable dentro del worker aunque Redis/Celery estén operativos.
2. Mantener el barrido needs_reembedding como recuperación, no como camino normal.
3. Añadir métrica de tiempo desde text_ready hasta semantic_search_ready.
4. Crear chunks técnicos que incluyan contexto:
   - Archivo y proyecto.
   - Layout/capa.
   - Elemento.
   - Cota, unidad y procedencia.
   - Fase/revisión.
5. No convertir cada entidad geométrica sin texto en un chunk inútil.
6. Incluir resumen estructurado de capas, elementos y cotas.
7. Mantener búsqueda exacta por filename, handle, label M1-M6 y texto CAD antes de semántica.

Archivos:

- backend/app/services/document_processing_core.py
- backend/app/services/document_embedding_pipeline.py
- backend/app/workers/embedding_tasks.py
- backend/app/services/search_service.py
- backend/app/services/exact_document_search.py
- backend/app/services/metrics/
- backend/tests/test_cad_embeddings.py
- backend/tests/test_cad_search.py

Aceptación:

- 95 % de DXF/DWG llegan a semantic_search_ready en menos de 120 segundos.
- Si el encolado inicial falla, el barrido recupera el documento y queda métrica del fallback.
- Buscar M3 devuelve el DWG correcto.
- Buscar una cota exacta devuelve la entidad y su documento.
- No se usa hash fallback silencioso.

Commit recomendado: CAD4-search-and-embeddings

## FASE CAD5 - Chat técnico

Objetivo: que la IA consulte hechos técnicos antes de improvisar sobre texto.

### Corrección de routing

1. Resolver primero archivo exacto, documento activo o selección del visor.
2. No interpretar “qué medidas aparecen” como habitación “aparecen”.
3. _extract_room_name solo puede usar:
   - Alias conocido de habitación.
   - Construcciones claras como “mide el salón” o “medida de la cocina”.
4. Si no existe una habitación válida, usar consulta general de cotas del plano.
5. Si se resolvió un archivo, cargar estructura CAD y texto del documento.

### Herramientas nuevas

- get_plan_summary.
- get_plan_dimensions.
- get_plan_layers.
- get_plan_elements.
- get_plan_entity.
- get_room_dimensions.
- get_plan_scale.
- compare_plan_revisions.

Cada herramienta debe:

- Aplicar tenant/access scope.
- Devolver document_id, plan_id y evidencia.
- Diferenciar valor original, normalizado, calculado y manual.
- Rechazar conversiones sin unidad fiable.

### Uso de Ovis/VLM

Usar Ovis/VLM solo cuando:

- La entidad CAD no contiene texto suficiente.
- La pregunta depende de una zona visual.
- Hay un símbolo o label ambiguo.

Enviar un recorte localizado, no el plano completo. El resultado VLM es suggestion hasta ser validado.

Archivos:

- backend/app/ai/tools.py
- backend/app/ai/context.py
- backend/app/ai/agent.py
- backend/app/ai/intent_router.py
- backend/app/tools/plans.py
- backend/app/services/technical_chat.py
- backend/tests/test_cad_chat_routing.py
- backend/tests/test_cad_chat_grounding.py
- backend/tests/test_cad_chat_e2e.py

Preguntas E2E obligatorias:

- ¿Qué medidas aparecen en logo bluesea medidas para mostrador recepcion.dwg?
- Resume 2025-02-10-mobles habitació 6110.dwg.
- ¿Qué elementos M1-M6 aparecen?
- ¿Qué cotas tiene M3?
- ¿En qué unidad está el dibujo?
- ¿Dónde está M4?
- ¿Hay alguna cota con unidad dudosa?

Aceptación:

- Ninguna pregunta crea una habitación falsa.
- La respuesta usa el documento solicitado.
- Toda cifra tiene evidencia.
- Una unidad dudosa se declara dudosa.
- Si no existen habitaciones, la IA lo explica sin afirmar que no existe información.
- La respuesta E2E incluye sources con el document_id correcto.

Commit recomendado: CAD5-grounded-chat

## FASE CAD6 - Backfill controlado y certificación Docker

Objetivo: activar el flujo sin arriesgar la base ni bloquear la aplicación.

Flags:

- CAD_STRUCTURED_EXTRACTION_ENABLED=false por defecto al integrar.
- CAD_PERSIST_PREVIEW_ENABLED=false.
- CAD_CHAT_TOOLS_ENABLED=false.

Activación:

1. Ejecutar migración.
2. Certificar fixtures.
3. Activar extracción estructurada.
4. Reprocesar solo 161483 y 161484.
5. Comparar baseline.
6. Activar preview persistente.
7. Activar herramientas de chat.
8. Ejecutar corpus de 10-20 DWG/DXF.
9. Ampliar backfill por lotes pequeños.

Crear:

- scripts/reprocess_cad_documents.py con --dry-run, --document-id, --limit y --batch-size.
- scripts/certify_cad.ps1.
- docs/runbooks/CAD_DXF_DWG.md.

El script de certificación debe ejecutar:

1. Compile.
2. Ruff de archivos tocados.
3. Tests unitarios DXF/DWG.
4. Tests de persistencia.
5. Tests de preview.
6. Tests de embeddings/search.
7. Tests de chat.
8. Integración ODA si está configurada.
9. Verificación docker compose config.
10. Resumen JSON del benchmark.

Aceptación:

- No se borra ningún documento.
- No se reprocesa fuera del filtro solicitado.
- Fallar ODA deja error accionable y conserva el original.
- Desactivar flags recupera el comportamiento anterior.
- Certificación completa verde.

Commit recomendado: CAD6-rollout-and-certification

## 8. Matriz de pruebas obligatoria

### Parser

- DXF sin texto y con geometría.
- DXF con unidad mm.
- DXF con unidad m.
- DXF unitless.
- DIMENSION con text override.
- DIMENSION con DIMLFAC.
- Polilínea abierta y cerrada.
- INSERT con atributos.
- Modelspace y layouts.
- Archivo DXF corrupto.

### DWG

- Firma válida.
- Firma falsa.
- Conversión por puente.
- Timeout.
- Respuesta vacía.
- Error de autenticación.
- Conversión correcta sin modificar original.
- Eliminación segura del temporal.

### Persistencia

- Idempotencia.
- Dedupe.
- Preservación manual.
- Conflicto manual/automático.
- Rollback de transacción.
- Cascade únicamente de filas automáticas obsoletas.

### Preview

- 1400 x 1000 mínimo.
- Transformación CAD/píxel.
- Coordenada Y invertida correctamente.
- Documento vacío sin crash.
- Preview cacheado.
- Imagen raster con preview grande.

### Chat

- Filename exacto.
- Etiqueta exacta M1.
- Pregunta general de cotas.
- Pregunta por habitación.
- Habitación inexistente.
- Unidad dudosa.
- Documento mal clasificado.
- Usuario sin permisos.
- Fuente persistida.

## 9. Métricas

Añadir:

- cad_conversion_total por outcome.
- cad_parse_total por source_format y outcome.
- cad_entities_total por entity_type.
- cad_dimensions_total por validation_status.
- cad_preview_total por source_format y outcome.
- cad_embedding_ready_seconds.
- cad_embedding_fallback_total.
- cad_chat_queries_total por intent y outcome.
- cad_chat_answers_without_sources_total por reason.
- cad_reprocess_total por outcome.

No incluir filenames, document_id, proyecto, valores de cotas ni handles como labels Prometheus.

## 10. Criterios globales de finalización

El plan solo se considera terminado cuando:

- Los dos DWG reales siguen processed.
- Ambos tienen preview funcional.
- Ambos están semantic_search_ready.
- Las DIMENSION CAD quedan persistidas o marcadas con causa verificable.
- M1-M6 son consultables en el segundo DWG.
- No se inventan habitaciones en un plano de mobiliario.
- Las unidades no se normalizan sin evidencia.
- Reprocesar no destruye correcciones manuales.
- “Qué medidas aparecen” no se enruta a una habitación falsa.
- El chat responde con sources correctas.
- El visor puede resaltar la evidencia.
- Flags apagados preservan el comportamiento previo.
- scripts/certify_cad.ps1 finaliza correctamente.

## 11. Estimación

Con implementación asistida por IA y revisión humana:

| Bloque | Tiempo estimado |
|---|---:|
| CAD0 corpus y baseline | 0,5-1 día |
| CAD1 parser tipado | 1,5-2 días |
| CAD2 persistencia y migración | 2-3 días |
| CAD3 preview y overlays | 1,5-2 días |
| CAD4 embeddings y búsqueda | 1 día |
| CAD5 chat técnico | 1,5-2 días |
| CAD6 backfill y certificación | 1 día |
| Total MVP sólido | 9-13 días laborables |

La detección avanzada de habitaciones y comparación de revisiones puede añadir 1-3 semanas según variedad de planos.

## 12. Orden de entrega

1. CAD0-corpus-and-safety.
2. CAD1-typed-parser.
3. CAD2-structured-persistence.
4. CAD3-preview-and-overlays.
5. CAD4-search-and-embeddings.
6. CAD5-grounded-chat.
7. CAD6-rollout-and-certification.

Cada entrega debe incluir:

- Diagnóstico confirmado.
- Archivos modificados.
- Tests ejecutados.
- Resultado antes/después.
- Riesgos y limitaciones.
- Migración/rollback, cuando aplique.
- Confirmación de que no se tocaron datos fuera de alcance.

## 13. Condiciones de parada

Detener la implementación y reportar antes de continuar si:

- La migración apunta a una base no identificada.
- Un test intenta borrar o truncar datos reales.
- El puente ODA modifica el original.
- Las unidades no pueden distinguirse y el código pretende aplicar un default.
- El reprocesado elimina hechos manuales confirmados.
- El chat responde una cifra sin source.
- Los flags apagados cambian la topología anterior.
- Hay cambios locales concurrentes que se solapan con un archivo objetivo.

No declarar terminado por tener tests unitarios verdes. La puerta final es una pregunta E2E real en Docker con evidencia visible en el visor.
