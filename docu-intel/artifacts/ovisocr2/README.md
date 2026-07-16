# Artefactos locales de certificaciÃ³n OvisOCR2

Este directorio es el destino de `scripts/benchmark_ovisocr2.py` y
`scripts/certify_ovisocr2.ps1`. No se deben versionar documentos, OCR bruto ni
imÃ¡genes de producciÃ³n. El manifiesto de corpus debe contener solamente rutas
aprobadas, hash, categorÃ­a y, cuando sea legal, expectativas anonimizadas.

Ejemplo de `corpus.json`:

```json
{
  "pages": [
    {
      "image": "sanitized/table_001.png",
      "document_id": 123,
      "page_number": 1,
      "category": "table"
    }
  ]
}
```

Primero ejecutar `--dry-run`; el benchmark real exige
`OVISOCR2_ENABLED=true`, servicio `readyz` y un corpus previamente autorizado.
