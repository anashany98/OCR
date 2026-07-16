# Operación segura de CAD DXF/DWG

1. Mantener `CAD_STRUCTURED_EXTRACTION_ENABLED=false` hasta certificar fixtures.
2. Ejecutar `pwsh scripts/certify_cad.ps1` y revisar `artifacts/cad/benchmark.json`.
3. Aplicar migraciones con `pwsh scripts/certify_cad.ps1 -WithDocker`.
4. Activar extracción y chat de forma independiente:
   `CAD_STRUCTURED_EXTRACTION_ENABLED=true`, `CAD_CHAT_TOOLS_ENABLED=true`.
5. Reprocesar únicamente con `python scripts/reprocess_cad_documents.py --dry-run --document-id 161483 --document-id 161484` y, tras revisar la lista, repetir sin `--dry-run`.
6. Un DWG sin puente ODA queda en error accionable; el archivo original no se modifica ni se elimina.
7. Para rollback, desactivar los flags de CAD; las filas estructuradas se conservan para auditoría.
