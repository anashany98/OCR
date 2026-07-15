# Brief para Mimo: comprensión de planos, memorias y documentación de obra

> Objetivo: convertir planos, croquis, memorias de obra, pliegos, mediciones, presupuestos y fichas técnicas en conocimiento estructurado, relacionado y consultable mediante chat. Toda respuesta debe conservar procedencia: documento, página, bbox/coordenadas, método de extracción y confianza.

## 0. Reglas de ejecución

- Mantener contratos públicos existentes de OCR, embeddings y búsqueda.
- No usar clasificación documental como filtro excluyente.
- Priorizar datos vectoriales sobre OCR cuando existan.
- VLM interpreta y valida; no debe inventar geometría ni medidas.
- Diferenciar siempre valores impresos, calculados y corregidos manualmente.
- No reemplazar un dato confirmado por uno de menor confianza.
- Añadir migraciones Alembic para cambios de esquema.
- Añadir tests unitarios, integración y E2E por tarea.
- Un commit independiente por tarea: `PM1`, `PM2`, etc.
- Revisar `git diff` antes de editar: worktree contiene cambios concurrentes.
- No ejecutar tests destructivos contra base de datos real.

## 0.1 Alerta operativa previa

Durante auditoría anterior la base contenía 1.481 documentos. En comprobación posterior la base activa devolvió `0 documentos`. Antes de implementar o reprocesar:

1. Confirmar si base fue reiniciada intencionadamente.
2. Confirmar `DATABASE_URL` de backend, workers, migraciones y tests.
3. Separar bases `dev`, `test` y datos reales.
4. Restaurar backup si corresponde.
5. Añadir protección para impedir `drop/truncate/delete all` en base no marcada como test.

No continuar con backfill de planos hasta resolver esta situación.

---

# 1. Capacidades existentes

Actualmente existen piezas útiles:

- Clasificación `plano` y `croquis_medida`.
- Ruta `plan_ocr` en content router.
- OCR Tesseract/Paddle/PP-Structure/VLM.
- Extracción regex de escala, superficies y cotas.
- Modelos `Plan`, `PlanRoom`, `PlanDimension`, `PlanSymbol` y `PlanMeasurement`.
- Detección YOLO de símbolos arquitectónicos.
- Detección experimental de líneas y polígonos con OpenCV.
- Sugerencias VLM de habitaciones.
- Editor manual de habitaciones, cotas y escala.
- Parser DXF básico conectado al router.
- Parser DXF avanzado no conectado.
- Herramienta de chat para buscar medidas por nombre de estancia.

## 1.1 Problemas confirmados

### Geometría no conectada

`backend/app/services/plan_geometry.py::detect_rooms_from_image()` no se llama desde pipeline.

`backend/app/services/plan_line_detection.py::detect_lines()` tampoco persiste resultados automáticamente.

### Escala aplicada sobre bbox incorrecto

`plan_extraction.py` deriva longitud física usando lado mayor del bbox del texto de una cota. Ancho de etiqueta `3,50 m` no representa longitud de línea acotada. Deben medirse extremos de línea de cota.

### DPI aproximado

`_load_plan_page_dpi()` devuelve `settings.pdf_ocr_dpi`, no DPI efectivo de render.

### Bbox digital sin granularidad

PDF digital crea a menudo un bloque de texto con bbox de página completa. Cotas extraídas heredan posición inútil.

### Fase/revisión no persistidas

`extract_plan_phase()` existe, pero no está conectado a `Plan.project_phase` y `Plan.revision` durante persistencia.

### Parser DXF duplicado

- `backend/app/parsers/dxf.py`: conectado, principalmente texto/capas.
- `backend/app/services/dxf_parser.py`: extrae DIMENSION, bloques y render, pero está muerto.

### Formatos ausentes

No hay soporte nativo para IFC, DWG, RVT, DGN ni BC3/FIEBDC.

### Memorias sin modelo propio

No existen tipos ni tablas específicas para memoria descriptiva, constructiva, pliego, capítulos, especificaciones, normativa o unidades de obra.

### Chat limitado

Chat consulta principalmente `PlanRoom.name`; no ofrece herramientas completas para símbolos, materiales, revisiones, capítulos, partidas o contradicciones.

---

# 2. Contrato funcional objetivo

## 2.1 Preguntas que sistema debe contestar

### Planos

- ¿Qué escala tiene plano?
- ¿Qué planta, sección o alzado representa?
- ¿Cuál es revisión más reciente?
- ¿Cuánto mide habitación X?
- ¿Qué superficie tiene?
- ¿Cuántas puertas, ventanas, sanitarios o luminarias aparecen?
- ¿Dónde está elemento dentro del plano?
- ¿Qué cotas impresas rodean estancia?
- ¿Qué cambia entre revisión A y B?
- ¿Plano y memoria especifican mismo material?

### Memorias y pliegos

- ¿Qué solución constructiva se prescribe para tabiques?
- ¿Qué material y espesor se exige?
- ¿Qué normativa se cita?
- ¿Qué trabajos incluye capítulo de carpintería?
- ¿Qué tolerancias o requisitos de ejecución aparecen?
- ¿Qué medidas de seguridad se exigen?
- ¿Qué mantenimiento se prescribe?

### Mediciones y presupuesto

- ¿Cuántos m² de pavimento hay?
- ¿Qué partida corresponde a habitación X?
- ¿Qué cantidad, unidad, precio e importe tiene partida?
- ¿Qué plano justifica medición?
- ¿Hay diferencias entre memoria, mediciones y presupuesto?

## 2.2 Evidencia obligatoria

Cada hecho técnico debe guardar:

```text
valor
unidad
document_id
page_number/sheet
bbox o coordenadas
método de extracción
confianza
revisión
estado de validación
texto fuente
```

Métodos posibles:

```text
pdf_vector
dxf_entity
ifc_property
ocr_text
table_parser
cv_geometry
vlm_suggestion
manual
calculated
```

---

# 3. Arquitectura objetivo

```text
Proyecto / obra
├── Documentos técnicos
│   ├── Memoria descriptiva
│   ├── Memoria constructiva
│   ├── Pliego
│   ├── Mediciones
│   ├── Presupuesto
│   └── Fichas técnicas
├── Planos
│   ├── Hojas
│   ├── Fases
│   ├── Revisiones
│   ├── Espacios
│   ├── Elementos
│   ├── Cotas
│   └── Símbolos
└── Relaciones
    ├── estancia → material
    ├── elemento → especificación
    ├── partida → medición
    ├── partida → presupuesto
    ├── plano → memoria
    └── plano → revisión
```

Orden de preferencia de fuente:

```text
IFC/BIM
→ DXF/DWG convertido
→ PDF vectorial
→ PDF escaneado
→ imagen/croquis
→ anotación manual
```

---

# BLOQUE PM0 — Seguridad de datos y evaluación

## PM0.1 · Separar bases reales y tests

### Cambio requerido

- Variable explícita `APP_ENV=test|development|production`.
- Tests solo arrancan si database contiene marcador de test.
- Fixture bloquea operaciones destructivas si nombre/host no corresponde a test.
- Comandos de backfill requieren `--dry-run` primero.
- Backup verificado antes de reprocesado masivo.

### Aceptación

- `pytest` no puede vaciar base real.
- Backend y workers apuntan a misma base prevista.
- Documento operativo explica restauración.

## PM0.2 · Corpus técnico de evaluación

Crear corpus anonimizado con mínimo:

- 3 PDFs vectoriales.
- 3 planos escaneados.
- 2 croquis manuscritos/fotos.
- 2 DXF.
- 2 memorias de obra.
- 2 pliegos.
- 2 mediciones/presupuestos tabulares.
- 2 revisiones del mismo plano.

Manifest por fixture:

```json
{
  "document_type": "plano_arquitectura",
  "expected": {
    "scale": "1:100",
    "phase": "PLANTA PRIMERA",
    "rooms": [{"name": "Dormitorio 1", "area_m2": 15.0}],
    "symbols": {"single_door": 4}
  }
}
```

### Aceptación

- Evaluación reproduce extracción y preguntas RAG.
- Resultados incluyen precisión, recall y tolerancias numéricas.

---

# BLOQUE PM1 — Taxonomía técnica y modelo de datos

## PM1.1 · Tipos documentales técnicos

Añadir clasificación:

```text
plano_arquitectura
plano_estructura
plano_electrico
plano_fontaneria
plano_climatizacion
plano_contra_incendios
croquis_medicion
memoria_descriptiva
memoria_constructiva
pliego_condiciones
mediciones_obra
estudio_seguridad
gestion_residuos
ficha_tecnica
manual_instalacion
```

Mantener `plano` como categoría padre o alias compatible.

Clasificación nunca excluye búsqueda.

### Archivos

- `backend/app/services/classification.py`
- `backend/app/parsers/content_router.py`
- Esquemas frontend/backend.
- Tests de clasificación.

## PM1.2 · Proyecto, hoja y revisión

Añadir/normalizar entidades:

### `technical_projects`

- `id`
- `name`
- `code`
- `client`
- `location`
- `budget_scope_id`

### `plan_sheets`

- `plan_id`
- `page_number`
- `sheet_number`
- `title`
- `discipline`
- `phase`
- `revision`
- `revision_date`
- `scale_text`
- `scale_ratio`
- `effective_dpi`
- `coordinate_system`
- `width`
- `height`

No asumir una única escala por documento; puede haber varias escalas por hoja o viewport.

## PM1.3 · Hechos técnicos genéricos

Crear modelo reutilizable `technical_facts`:

- `project_id`
- `document_id`
- `page_number`
- `sheet_id`
- `fact_type`
- `subject`
- `property_name`
- `value_text`
- `value_numeric`
- `unit`
- `bbox_json`
- `coordinates_json`
- `source_text`
- `source_method`
- `confidence`
- `validation_status`
- `revision`

Tipos ejemplo:

```text
material
thickness
fire_rating
acoustic_rating
dimension
area
quantity
standard
execution_requirement
maintenance_requirement
```

### Aceptación

- Todo hecho puede citar documento/página/posición.
- No se pierde valor original al normalizar unidad.

---

# BLOQUE PM2 — Planos vectoriales

## PM2.1 · Granularidad PDF vectorial

### Cambio requerido

Para PDF digital extraer:

- Palabras/spans individuales con bbox.
- Líneas, paths, rectángulos y curvas vectoriales.
- Rotación del texto.
- Tipografía/tamaño como señal de cajetín, título y cotas.
- Imágenes incrustadas.

No usar bloque único de página completa para extracción geométrica.

Persistir bloques por span/región conservando coordenadas PDF.

### Aceptación

- Texto `3,50` conserva bbox local.
- Cajetín y leyenda quedan separados del dibujo.
- Coordenadas se pueden superponer en visor.

## PM2.2 · Unificar parsers DXF

### Cambio requerido

Conectar capacidades de `services/dxf_parser.py` al router y eliminar duplicación progresivamente.

Extraer:

- `TEXT` y `MTEXT`.
- `DIMENSION` con measurement real.
- `LINE`, `LWPOLYLINE`, `POLYLINE`, `ARC`.
- `INSERT` y atributos.
- Capas.
- Unidades mediante `$INSUNITS`.
- Layout/model space.
- Extents.
- Render preview.

No devolver documento vacío porque DXF carezca de texto si contiene geometría.

### Aceptación

- DXF sin texto genera plano consultable.
- Cotas DIMENSION se persisten con valor/unidad/coordenadas.
- Bloques de puerta/ventana se convierten a elementos.

## PM2.3 · DWG mediante conversión controlada

No implementar parser binario propio. Añadir adaptador opcional:

```text
DWG → conversor configurado → DXF temporal → parser DXF
```

- Mantener original.
- Registrar herramienta/versión.
- Timeout y errores claros.
- Setting desactivado por defecto.

## PM2.4 · IFC/BIM

Añadir soporte opcional IFC:

- Espacios `IfcSpace`.
- Muros, puertas, ventanas, equipos.
- Materiales.
- Propiedades y cantidades.
- Niveles/plants.
- Relaciones espaciales.
- GUID estable.

IFC debe alimentar mismo modelo `rooms/elements/technical_facts`.

### Aceptación

- Pregunta sobre material o elemento usa propiedad IFC con fuente.
- No se rasteriza IFC como vía principal.

---

# BLOQUE PM3 — Planos rasterizados y geometría

## PM3.1 · Segmentación de hoja

Detectar regiones:

- Cajetín.
- Dibujo principal.
- Leyenda.
- Notas.
- Tabla de revisiones.
- Viewports/detalles.

Aplicar OCR y reglas por región. No mezclar número de revisión del cajetín con cota del dibujo.

## PM3.2 · DPI y coordenadas reales

Persistir por página:

- DPI solicitado.
- DPI efectivo.
- Dimensiones raster.
- Dimensiones PDF en puntos.
- Matriz píxel ↔ PDF.
- Rotación aplicada.

Crear funciones únicas de transformación de coordenadas y cubrirlas con tests.

## PM3.3 · Cotas reales

Sustituir validación por bbox de texto.

Pipeline:

1. Detectar líneas de cota.
2. Detectar flechas/ticks/extremos.
3. Detectar texto de cota próximo.
4. Asociar texto con línea mediante distancia, orientación y región.
5. Convertir valor impreso a unidad normalizada.
6. Calcular longitud geométrica usando escala.
7. Comparar impresa/calculada.

Persistir:

- `printed_value_m`
- `calculated_value_m`
- `start_point`
- `end_point`
- `label_bbox`
- `relative_error`
- `confidence`

### Aceptación

- Cota `3,50 m` se asocia a línea correcta.
- Tolerancia configurable.
- Discrepancia no sobrescribe valor impreso.

## PM3.4 · Habitaciones y espacios

Conectar `detect_rooms_from_image()` con pipeline, pero no persistir contornos brutos sin depuración.

Mejorar:

- Eliminar contornos de texto/mobiliario.
- Cerrar pequeños huecos de puertas de forma controlada.
- Detectar polígonos anidados.
- Asociar label mediante punto-en-polígono/proximidad.
- Distinguir habitación, armario, hueco, terraza y zona exterior.
- Calibrar área con escala real.

Fuentes:

- `vector_geometry`
- `cv_geometry`
- `vlm_suggestion`
- `manual`

Manual siempre tiene prioridad, conservando historial.

## PM3.5 · Símbolos y elementos

Mantener YOLO como detector sugerente. Añadir:

- Modelo/versión.
- Taxonomía por disciplina.
- Relación símbolo → estancia.
- Deduplicación por IoU.
- Validación contra leyenda del plano.
- Estado confirmado/rechazado.

No ejecutar modelo arquitectónico genérico sobre plano eléctrico como única fuente.

## PM3.6 · VLM como validador

VLM debe recibir crops regionales y JSON estricto:

- Nombre de estancia.
- Tipo de plano.
- Texto de cajetín.
- Asociación probable etiqueta-región.
- Descripción de símbolo dudoso.

No pedir al VLM que calcule longitudes en píxeles ni áreas exactas.

---

# BLOQUE PM4 — Memorias, pliegos y mediciones

## PM4.1 · Parsing por estructura

Respetar:

- Portada.
- Índice.
- Capítulos/subcapítulos.
- Párrafos.
- Listas.
- Tablas.
- Anexos.
- Encabezados/pies.

Chunks deben conservar ruta jerárquica:

```text
Memoria constructiva
→ 4 Cerramientos
→ 4.2 Tabiquería interior
→ párrafo fuente
```

Prepend de embedding:

```text
[proyecto=X | documento=memoria_constructiva | capítulo=4.2 Tabiquería | pág=34]
```

## PM4.2 · Extracción de especificaciones

Extraer con reglas + LLM/VLM estructurado:

- Sistema/elemento.
- Material.
- Producto/referencia.
- Espesor.
- Dimensiones.
- Prestaciones.
- Reacción/resistencia al fuego.
- Aislamiento acústico/térmico.
- Método de instalación.
- Tolerancias.
- Control de calidad.
- Mantenimiento.
- Normativa citada.
- Ubicación/estancia/planta.

Cada campo requiere evidencia.

## PM4.3 · Partidas y mediciones

Crear modelos:

### `work_chapters`

- Código.
- Título.
- Orden.
- Padre.

### `work_items`

- Código.
- Descripción.
- Unidad.
- Cantidad.
- Precio unitario.
- Importe.
- Zona/planta/estancia.
- Capítulo.
- Fuente.

### `work_item_breakdowns`

- Factores de medición.
- Largo/ancho/alto.
- Número de unidades.
- Fórmula.

Soportar tablas PDF/Excel y preparar adaptador BC3.

## PM4.4 · BC3/FIEBDC

Añadir parser opcional para:

- Conceptos.
- Capítulos.
- Descomposición.
- Mediciones.
- Precios.
- Unidades.

Conservar código original y jerarquía.

### Aceptación

- Agregaciones se resuelven por SQL exacto.
- `SUM(cantidad)` y `SUM(importe)` no dependen del LLM.

---

# BLOQUE PM5 — Relaciones y consistencia

## PM5.1 · Asociación de proyecto

Relacionar documentos por:

- `budget_scope_id`.
- Carpeta/ruta.
- Código de proyecto.
- Cliente/ubicación.
- Número de plano.
- Referencias cruzadas.
- Revisión.

No unir solo por similitud semántica.

## PM5.2 · Grafo técnico

Relaciones mínimas:

```text
room LOCATED_IN plan_sheet
element LOCATED_IN room
element SPECIFIED_BY technical_clause
work_item APPLIES_TO room
work_item SUPPORTED_BY plan_sheet
plan_sheet SUPERSEDES plan_sheet
document PART_OF project
```

## PM5.3 · Comparación de revisiones

Para misma hoja:

- Comparar cajetín/revisión.
- Alinear coordenadas.
- Detectar texto añadido/eliminado.
- Detectar elementos/símbolos cambiados.
- Detectar cambios de cotas.
- Generar diff con regiones resaltadas.

No comparar planos distintos solo porque filename se parezca.

## PM5.4 · Contradicciones

Detectar:

- Material diferente entre plano y memoria.
- Cantidad presupuestada distinta de medición.
- Cota impresa incompatible con escala.
- Revisión obsoleta citada por otro documento.

Salida:

```text
hecho A + fuente A
hecho B + fuente B
tipo de discrepancia
confianza
requiere revisión
```

---

# BLOQUE PM6 — Chat técnico

## PM6.1 · Herramientas nuevas

Añadir herramientas autorizadas y con scope:

- `find_technical_project`
- `get_plan_sheet`
- `get_plan_rooms`
- `get_room_dimensions`
- `get_plan_elements`
- `count_plan_symbols`
- `get_plan_scale`
- `get_technical_specifications`
- `find_material_by_room`
- `get_work_items`
- `aggregate_work_items`
- `compare_plan_revisions`
- `compare_plan_to_specification`
- `find_measurement_source`

## PM6.2 · Enrutado de preguntas

Prioridad:

```text
identificador exacto/proyecto
→ SQL/estructura técnica
→ geometría
→ BM25
→ semántica
→ VLM bajo demanda
```

No aplicar filtro `document_type=plano` si pregunta contiene identificador exacto y documento está mal clasificado.

## PM6.3 · Respuesta técnica

Diferenciar:

```text
Valor impreso
Valor calculado
Valor manual confirmado
Valor sugerido por visión
```

Ejemplo:

```text
Dormitorio 1 figura con una cota impresa de 3,50 m.
La medición geométrica a escala da 3,47 m (diferencia 0,03 m; 0,9 %).
Fuente: Plano A-03, revisión B, página 1, región [x1,y1,x2,y2].
```

### Aceptación

- Toda cifra tiene fuente.
- Chat no mezcla revisiones sin avisar.
- Agregaciones usan datos estructurados.
- Dato dudoso incluye advertencia.

---

# BLOQUE PM7 — Visor y revisión humana

## PM7.1 · Overlays

Mostrar en visor:

- Habitaciones/polígonos.
- Labels.
- Cotas y extremos.
- Símbolos.
- Regiones de cajetín/leyenda.
- Hechos citados por chat.
- Cambios entre revisiones.

## PM7.2 · Confirmación

Gestor puede:

- Confirmar/rechazar estancia.
- Corregir nombre.
- Ajustar polígono.
- Calibrar escala con dos puntos.
- Confirmar cota.
- Corregir símbolo.
- Vincular material/partida.

Guardar historial, usuario, fecha y valor previo.

## PM7.3 · Aprendizaje controlado

Correcciones pueden generar ejemplos para evaluación/entrenamiento, pero no cambiar reglas globales automáticamente sin aprobación.

---

# 4. Tests obligatorios

## Planos

- PDF digital con spans y bboxes.
- PDF escaneado rotado.
- Plano con varias escalas.
- Cota horizontal y vertical.
- Cota sin unidad.
- Texto próximo a dos líneas posibles.
- Habitación con hueco de puerta.
- Polígono irregular.
- DXF sin texto pero con geometría.
- DXF con DIMENSION y `$INSUNITS`.
- Dos revisiones de misma hoja.
- Símbolo duplicado por tiles/crops.

## Memorias

- Capítulos jerárquicos.
- Tabla partida/cantidad/unidad.
- Material + espesor + ubicación.
- Normativa citada.
- Contradicción memoria/plano.
- Agregación exacta de mediciones.

## Chat E2E

```text
¿Cuánto mide Dormitorio 1 según plano A-03?
¿Qué material llevan tabiques de esa habitación?
¿Qué partida presupuestaria corresponde?
¿Cambió en revisión B?
```

Debe mantener proyecto/hoja/estancia activos y citar fuentes distintas correctamente.

---

# 5. Métricas

- `technical_document_classification_total{type,outcome}`
- `plan_vector_entities_total{entity_type}`
- `plan_dimension_matches_total{outcome}`
- `plan_room_detection_total{outcome,source}`
- `plan_symbol_detection_total{class,outcome}` con taxonomía acotada
- `technical_fact_extraction_total{fact_type,outcome}`
- `technical_conflicts_total{type}`
- `plan_revision_comparisons_total{outcome}`
- `technical_chat_answers_total{outcome}`
- `technical_chat_answers_without_sources_total{reason}`

No usar proyecto, filename, IDs o valores técnicos como labels Prometheus.

---

# 6. Orden de implementación

| Orden | Tarea | Resultado |
|---:|---|---|
| 1 | PM0 | Datos protegidos + corpus de evaluación |
| 2 | PM1 | Taxonomía y modelo común |
| 3 | PM2.1 | Bboxes/spans PDF fiables |
| 4 | PM2.2 | DXF vectorial conectado |
| 5 | PM3.2/PM3.3 | Coordenadas y cotas reales |
| 6 | PM4.1/PM4.2 | Memorias estructuradas |
| 7 | PM4.3 | Mediciones/partidas SQL |
| 8 | PM3.4/PM3.5 | Habitaciones y símbolos |
| 9 | PM5 | Relaciones, revisiones y conflictos |
| 10 | PM6 | Chat técnico |
| 11 | PM7 | Overlays y validación humana |
| 12 | PM2.4/PM4.4 | IFC y BC3 |

No comenzar por modelo visual más complejo. Primero asegurar coordenadas, fuentes y corpus medible.

---

# 7. MVP

MVP debe cubrir:

- Clasificar planos y memorias.
- Extraer cajetín, hoja, escala, fase y revisión.
- Extraer texto con bbox granular.
- Extraer cotas impresas con página/bbox.
- Parsear DXF DIMENSION/capas/bloques.
- Extraer capítulos/materiales/especificaciones de memoria.
- Consultar estancias, cotas y materiales por chat.
- Citar documento/página/región.
- Detectar valores incompatibles sin inventar corrección.

Fuera del MVP inicial:

- BIM 3D completo.
- Reconstrucción geométrica perfecta desde escaneos degradados.
- Conversión RVT nativa.
- Cómputos métricos automáticos con validez contractual.

---

# 8. Checklist final

- [ ] Tests nunca usan base real.
- [ ] Planos vectoriales no se reducen a OCR plano.
- [ ] DXF sin texto conserva geometría.
- [ ] Cotas miden línea real, no bbox de etiqueta.
- [ ] DPI/matriz de coordenadas quedan persistidos.
- [ ] Fase y revisión se guardan.
- [ ] Habitaciones tienen polígono y procedencia.
- [ ] Símbolos se relacionan con estancia.
- [ ] Memoria conserva capítulos.
- [ ] Materiales y requisitos tienen evidencia.
- [ ] Mediciones se agregan por SQL.
- [ ] Chat distingue impreso/calculado/manual.
- [ ] Comparación de revisiones cita ambas fuentes.
- [ ] Contradicciones se muestran, no se ocultan.
- [ ] Toda respuesta técnica incluye fuentes.

# 9. Entrega esperada por tarea

1. Diagnóstico contra código real.
2. Archivos modificados.
3. Migración y rollback.
4. Tests ejecutados.
5. Fixture usado.
6. Métrica antes/después.
7. Limitaciones conocidas.
8. Commit independiente `PMx`.

No declarar tarea completa sin probar pregunta E2E y verificar fuente visual en visor.
