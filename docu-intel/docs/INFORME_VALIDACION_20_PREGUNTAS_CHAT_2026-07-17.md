# Validacion real del chat: 20 preguntas contra documentos distintos

Fecha: 2026-07-17
Entorno: API local `POST /api/v1/ai/ask` con usuario administrador
Corpus observado: 198 documentos; las preguntas se hicieron contra documentos ya procesados y, salvo indicacion expresa, `semantic_search_ready=true`.

## Resultado ejecutivo

El chat no es fiable para consulta documental de produccion en su estado actual.

- **Correctas y con fuente documental correcta: 4/20 (20 %).**
- **Fallidas: 16/20 (80 %).** Incluyen respuestas que no recuperan el archivo, rechazos falsos de informacion que si esta en el contexto, rutas deterministas equivocadas y una respuesta con una cifra inventada.
- **Recuperacion del documento objetivo: 15/20 (75 %).** Por tanto, el mayor problema no es solo buscar: en muchos casos recupera la fuente correcta pero no la convierte en una respuesta correcta.
- **Alucinacion verificable: Q09.** Preguntada la ficha `Fine` por su peso total, afirmo `12.013,64 EUR` y lo atribuyo a `PRINTER.pdf`. El dato real en `Ficha Tecnica_Fine.pdf` es aproximadamente `2.840 g/m2`.

No se han usado preguntas abstractas ni conocimiento externo. Cada expectativa se tomo previamente del texto extraido del archivo objetivo.

## Bateria y resultados

| ID | Pregunta comprobada | Archivo/fuente esperada | Resultado |
|---|---|---|---|
| Q01 | Total de la factura BCA2500222229 | doc 193 | Correcta: 1.545,00 EUR |
| Q02 | Vencimiento de BCA2500222229 | doc 193 | Correcta: 08-Jul-25 |
| Q03 | Paquetes de BCA2500222229 | doc 193 | Correcta: 39 |
| Q04 | Total con IVA del presupuesto 1-250258 | doc 13 | Fallo: `presupuesto no encontrados`; esperado 3.972,20 EUR |
| Q05 | Cojines decorativos 65x65 de 1-250258 | doc 13 | Fallo: misma ruta de catalogo; esperado 97 |
| Q06 | Hitos de pago de 1-250258 | doc 13 | Fallo: devuelve dos comprobantes de pago no pertinentes; esperado 40/30/30 |
| Q07 | Composicion de Opulent | doc 86 | Fallo: no recupera la ficha; esperado 100% poliamida Imprel Opal |
| Q08 | Ancho de Opulent | doc 86 | Fallo: no recupera la ficha; esperado 2,00-4,00 m |
| Q09 | Peso total de Fine | doc 75 | **Alucinacion**: 12.013,64 EUR desde `PRINTER.pdf`; esperado 2.840 g/m2 |
| Q10 | Precio por m2 de ELEGANCE EL2944 | doc 53 | Fallo: intenta buscar pedido de origen de factura, no responde 18,50 EUR/m2 |
| Q11 | Total de la proforma ELEGANCE EL2944 | doc 53 | Fallo: misma desviacion; esperado 1.320,00 EUR |
| Q12 | Proyecto de OC_0114 EGEA CAMBIADORES | doc 160 | Fallo: recupera el PDF correcto y luego niega la informacion; esperado GRAN MELIA VICTORIA |
| Q13 | Precio sin IVA de OC_0114 | doc 160 | Fallo: recupera el PDF correcto y luego niega la informacion; esperado 2.385,46 EUR |
| Q14 | Hitos de facturacion de OC_0114 | doc 160 | Fallo: recupera el PDF correcto y luego niega la informacion; esperado 40/30/30 |
| Q15 | Numero de OC con nota GM-EGEA e Ines Fernandez | doc 157 | Fallo: recupera el PDF correcto y luego niega la informacion; esperado 2201355235 |
| Q16 | Importe y linea de OC 2201355235 | doc 157 | Fallo: recupera documentos ajenos; esperado 22.732,00 EUR y AGENCIAS MARKETING |
| Q17 | Total de envio del correo CS2355551 | doc 198 | Fallo de respuesta: vuelca un fragmento OCR, no contesta 1.348,21 EUR + IVA |
| Q18 | Desglose Palma-Barcelona/Carga Express de CS2355551 | doc 198 | Fallo: recupera el correo correcto y niega la informacion; esperado 148,21 EUR / 1.200 EUR |
| Q19 | Producto y medidas del packing list Palma Real | doc 117 | Correcta en el texto devuelto, aunque como volcado OCR: funda colchoneta sin relleno, 203 x 65 x 7 |
| Q20 | Muestras llevadas por David en MEDICIONES VARIAS | doc 76 | Fallo: no identifica el correo; esperado Balinesa Sea View, Balinesa Calita y fundas hamacas |

## Evidencia de las causas

### 1. Enrutamiento estructurado que secuestra preguntas de contenido

La seleccion real de herramientas para Q04-Q06 fue:

```text
Q04 total del presupuesto 250258
-> list_documents_by_budget_code(250258, document_type=presupuesto)

Q05 cojines del presupuesto 250258
-> list_documents_by_budget_code(250258, document_type=presupuesto)

Q06 hitos de pago del presupuesto 250258
-> list_documents_by_budget_code(250258, document_type=comprobante_pago)
```

Esas herramientas enumeran archivos; no leen el PDF que contiene los importes, lineas o condiciones. El renderer determinista devuelve entonces una lista o `no encontrados` y sustituye la respuesta documental.

En `backend/app/ai/tools.py`, `select_structured_tools()` aplica `list_documents_by_budget_code` para cualquier pregunta con codigo de presupuesto (zona de las lineas 1264-1280), aun cuando no pide listar documentos.

### 2. El texto del documento resuelto queda fuera del contexto

Para Q04 se resolvio correctamente el documento 13, pero el contexto incluyo su ficha y seis documentos de la carpeta. La funcion `_maybe_load_resolved_document_text()` no carga las paginas si ya existe **cualquier** item de ese documento. Como la ficha ya existe, se queda sin el texto que contiene `3.972,20`, `97` y `40/30/30`.

La condicion esta en `backend/app/ai/context.py`, funcion `_maybe_load_resolved_document_text()` (lineas 1693-1695 aprox.). Debe comprobar si ya hay **texto de pagina**, no si ya existe metadata del documento.

### 3. Recuperacion exacta correcta, generacion incorrecta

En Q12, Q13, Q14 y Q18 el contexto contenia el documento correcto y el dato literal. Ejemplos:

- OC_0114: `Proyecto: GRAN MELIA VICTORIA`, precio `2.385,46 EUR` y calendario `40/30/30`.
- CS2355551: total `1.348,21 EUR + IVA`, Palma-Barcelona `148,21 EUR` y Carga Express `1.200 EUR`.

Sin embargo, `qwen3-8b` devolvio “No dispongo de esa informacion”. El flujo la acepto porque la validacion actual comprueba idioma, nombres de documentos y cobertura superficial, pero no verifica que una negativa sea incompatible con evidencia explicita ni que la respuesta cubra los campos solicitados.

### 4. Clasificacion erronea de preguntas de documento como agregados o facturas

- Q09 contiene “peso total” y se enruta a `aggregate_business` antes de localizar la ficha Fine; el agregado devolvio una suma de presupuestos, no una especificacion tecnica.
- Q10-Q11 se clasifican como `get_invoice_origin_order` por el texto “proforma”, por lo que el fallback habla del pedido origen de una factura en vez de leer el precio o total de la proforma.
- Para Q12, el extractor genero tambien la frase espuria `proyecto figura`, aunque despues si encontro `OC_0114 EGEA CAMBIADORES`.

## Prioridad de correccion

1. **Bloquear respuestas falsas (P0).** Antes de aceptar una respuesta del LLM, validar que contiene los valores/campos solicitados cuando el contexto tiene evidencia de alta confianza. Una negativa con coincidencia literal debe convertirse en respuesta extractiva determinista, no aceptarse.
2. **Corregir el cargado de evidencia (P0).** Cargar las paginas del documento resuelto aunque ya haya metadata, y priorizarlas por encima de relaciones de carpeta.
3. **Restringir rutas estructuradas (P0).** `list_documents_by_budget_code` solo para verbos de listado/catalogo. Preguntas sobre total, linea, cantidad, condicion, fecha, medida o pago deben usar texto/entidades del documento exacto.
4. **Resolver nombres tecnicos y archivos (P1).** `Fine`, `Opulent`, `OC_0114` y nombres de correo han de activar busqueda literal de documento antes de cualquier agregado semantico.
5. **Eliminar el volcado OCR como respuesta final (P1).** Usarlo como evidencia de respaldo, pero extraer y responder el dato pedido en una frase concisa.
6. **Anadir esta bateria a regresion automatizada (P1).** Casos obligatorios: Q04-Q06, Q09, Q10-Q14, Q17-Q18 y Q20. Criterio: dato esperado y `document_id` esperado; prohibido aceptar una negativa si el extracto contiene el dato.

## Criterio de salida recomendado

No declarar el chat corregido hasta superar al menos 18/20 (90 %) de esta misma bateria, cero cifras inventadas y cero negativas cuando el texto recuperado contiene literalmente la respuesta.
