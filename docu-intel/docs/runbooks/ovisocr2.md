# Runbook de OvisOCR2

## PropÃ³sito y lÃ­mites

OvisOCR2 es un candidato OCR de Tier 4 para pÃ¡ginas complejas. No sustituye
parsers de PDF, Office, DXF, IFC o BC3 ni las rutas nativas de texto. El
backend nunca instala vLLM: llama al servicio `ovisocr2` por la red Docker
interna y conserva DotsOCR/NuExtract y la cascada clÃ¡sica como alternativas.

ConfiguraciÃ³n inicial aprobada:

- modelo: `ATH-MaaS/OvisOCR2`;
- revisiÃ³n: `77bfe9462d1e6f8965ee6698f08ea8ede580912c`;
- esquema HTTP: `1`;
- presupuesto total de cadena Tier 4: `450` s;
- concurrencia: `1`;
- GPU compartida de validaciÃ³n: `0`, uso de VRAM `0.50`;
- flag, canario y promociÃ³n: desactivados por defecto.

Cambiar la revisiÃ³n exige repetir corpus dorado, benchmark y rollback. La
referencia del modelo y licencia Apache-2.0 estÃ¡n en
<https://huggingface.co/ATH-MaaS/OvisOCR2>.

## Prevuelo y baseline

1. Mantener `OVISOCR2_ENABLED=false` durante construcciÃ³n y precarga.
2. Registrar commit, `nvidia-smi`, driver/CUDA, VRAM en reposo y servicios
   Paddle/embeddings en ejecuciÃ³n.
3. Preparar un corpus local aprobado de 50â€“100 pÃ¡ginas estratificadas; no
   versionar documentos ni OCR bruto de producciÃ³n.
4. Ejecutar y guardar el baseline sin Ovis:

```powershell
python scripts/benchmark_ovisocr2.py --manifest artifacts/ovisocr2/corpus.json --output artifacts/ovisocr2/baseline.json --dry-run
powershell -ExecutionPolicy Bypass -File scripts/certify_ovisocr2.ps1
```

Incluir control digital nativo (cero llamadas Ovis), escaneos limpios,
tablas/presupuestos, multicolumna, fÃ³rmulas, manuscritos, planos, fotografÃ­as
y pÃ¡ginas rotadas/borrosas. Medir CER/WER cuando haya transcripciÃ³n, exactitud
de IDs/fechas/importes, estructura de tablas, orden de lectura,
`needs_review`, latencia y pico de VRAM.

## ConstrucciÃ³n y arranque aislado

```powershell
docker compose --profile ovisocr2 build ovisocr2
docker compose --profile ovisocr2 up -d ovisocr2
docker compose --profile ovisocr2 ps ovisocr2
docker compose --profile ovisocr2 logs --tail 100 ovisocr2
```

`/healthz` confirma proceso vivo. `/readyz` devuelve 503 mientras el modelo
carga o si el pin falla. No hay puerto publicado al host: sÃ³lo los workers OCR
comparten `ovisocr2_internal` con el servicio. `ovisocr2_model_cache` conserva
los pesos; un reinicio normal no debe redescargarlos.

## Matriz de activaciÃ³n

| Entorno | `OVISOCR2_ENABLED` | `CANARY_PERCENT` | GPU/memoria | Objetivo |
|---|---:|---:|---|---|
| Desarrollo | `false` | `0` | no requerida | cliente/parser/Compose |
| ValidaciÃ³n GPU | `true` | `0` | GPU 0 / 0.40â€“0.50 | corpus y VRAM explÃ­citos |
| Canario | `true` | `5`, luego `25` | medida real | pÃ¡ginas elegibles |
| ProducciÃ³n | `true` | `100` | GPU dedicada / 0.70â€“0.80 | elegibles, nunca todas |

El canario usa `sha256(document_id:page_number)`, por lo que es estable entre
reintentos. La elegibilidad cubre OCR bajo, tabla/fÃ³rmula, plan/manuscrito y
salida vacÃ­a; `native_text`/`digital_native` siguen excluidas incluso al 100 %.

## CertificaciÃ³n y promociÃ³n

```powershell
powershell -ExecutionPolicy Bypass -File scripts/certify_ovisocr2.ps1 -WithDocker -Manifest artifacts/ovisocr2/corpus.json
python scripts/benchmark_ovisocr2.py --manifest artifacts/ovisocr2/corpus.json --output artifacts/ovisocr2/candidate.json
```

No promover sin: cero regresiÃ³n relevante de nÃºmeros crÃ­ticos, mejora de
tablas elegibles, cero llamadas al control nativo, soak de 200 pÃ¡ginas sin OOM,
fallback probado con el servicio detenido, ninguna salida truncada autoaceptada
y pruebas existentes verdes con Ovis apagado. Promover 5 %, 25 % y 100 % de
pÃ¡ginas elegibles; mantener Dots/NuExtract en todos los pasos. El SLO p95 se
fija tras medir la RTX 4070 real.

## Observabilidad y parada

Revisar `docuintel_ovisocr2_requests_total`,
`docuintel_ovisocr2_duration_seconds`,
`docuintel_ovisocr2_output_features_total` y los contadores Tier 4/fallback.
No usan `document_id`; `request_id` sÃ³lo estÃ¡ en logs JSON. Los intentos
persisten motor, revisiÃ³n `ovisocr2:<sha>`, bloques, decisiÃ³n y razones.
`truncated_output`, repeticiÃ³n, caja invÃ¡lida o conflicto numÃ©rico fuerzan
revisiÃ³n.

Detener promociÃ³n ante OOM repetido, circuito abierto sostenido, aumento de
revisiÃ³n, discrepancias numÃ©ricas, vacÃ­os/repeticiÃ³n, degradaciÃ³n de
Paddle/embeddings o incumplimiento del SLO.

## Rollback y reprocesado

1. Establecer `OVISOCR2_ENABLED=false` o `OVISOCR2_CANARY_PERCENT=0`.
2. Reiniciar sÃ³lo workers que leen configuraciÃ³n al arrancar y verificar que
   no salen peticiones Ovis y que la cascada usa alternativas.
3. No borrar intentos ni resultados histÃ³ricos.
4. Ante OOM, detener sÃ³lo el servicio y conservar logs:

```powershell
docker compose --profile ovisocr2 stop ovisocr2
docker compose --profile ovisocr2 logs --tail 200 ovisocr2
```

El selector de reprocesado es seguro por defecto:

```powershell
python scripts/reprocess_ovisocr2.py --reason low_confidence --reason needs_review --limit 25
python scripts/reprocess_ovisocr2.py --document-id 123 --page-number 2 --limit 1 --execute
```

Inspeccionar primero `artifacts/ovisocr2/reprocess-report.json`. El script
evita duplicar jobs pendientes/en curso, crea intentos nuevos y deja que la
comparaciÃ³n conserve un candidato anterior mejor.
