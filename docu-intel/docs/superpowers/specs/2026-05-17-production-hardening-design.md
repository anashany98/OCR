# Production Hardening Tanda Única Design

## Objetivo

Endurecer Docu-Intel en cuatro áreas sin activar hoteles/cadenas: permisos internos prácticos, calidad de datos, producción real y rendimiento con muchos GB.

## Arquitectura

La tanda añade servicios pequeños sobre la base existente. `access_review` resume permisos efectivos por principal sin duplicar el motor de `tenant_access`. `data_quality` agrupa reglas de calidad y acciones masivas apoyándose en `quality`. `production_readiness` hace comprobaciones operativas estrictas sobre DB, Redis, workers, watcher, disco, backups, manifest e integridad de ficheros. Los endpoints admin exponen estas capacidades y la UI los muestra en Administración con controles mínimos.

## Alcance

- Permisos por rol, tipo documental, tags sensibles y budget scope/carpeta principal.
- Simulación de acceso y redacción antes de entregar contexto a usuarios o IA externa.
- Reglas de calidad para OCR bajo, texto vacío, tipo desconocido, presupuesto sin número, pedido sin proveedor, factura sin fecha, plano sin escala, duplicados y fallos.
- Readiness de producción e integridad de almacenamiento local.
- Paginación, filtros y resúmenes para operaciones con muchos documentos.
- Tests backend y frontend para nuevos contratos.

## Fuera De Alcance

- Activar hoteles/cadenas como producto.
- Editor OCR avanzado versionado.
- Borrar originales físicos.
- Cambiar la IA externa o permitir SQL libre.

## Flujo De Datos

1. Admin consulta endpoints de revisión y readiness.
2. Backend calcula permisos, calidad e integridad con consultas acotadas y filtros.
3. Las acciones masivas crean jobs pendientes con límites y filtros explícitos.
4. La UI consume endpoints paginados y muestra resultados resumidos.

## Testing

Los tests cubren comportamiento, no implementación: permisos efectivos, filtro por tags/tipo, reglas de calidad, integridad de archivos, readiness, paginación y cliente frontend.
