# Ejecucion continua de la certificacion Terra

`scripts/terra_certify.ps1` convierte la fase de certificacion en una ejecucion recuperable. Conserva los cambios de trabajo: no hace reset, limpieza de Git ni modifica el corpus. Cada etapa escribe su salida y estado en `data/terra-certification/`.

## Ejecucion normal

```powershell
pwsh -File scripts/terra_certify.ps1
```

Si una etapa falla, se conserva `state.json` y su log. Tras corregir el problema, reanudar sin repetir las que ya pasaron:

```powershell
pwsh -File scripts/terra_certify.ps1 -Resume
```

Opciones intencionadas:

- `-SkipFrontend`: solo para diagnostico de backend; una certificacion final no debe usarlo.
- `-SkipDocker`: solo para desarrollo local; omite la validacion PostgreSQL/OCR y no certifica la fase 12.
- `-RunSlowOcr`: incluye la prueba OCR lenta que normalmente se omite.
- `-KeepTemporaryDatabase`: conserva la base temporal para inspeccion manual. El nombre siempre empieza por `terra_cert_`.

## Garantias de la ejecucion

1. Revisa `git diff --check`, compila backend y prueba resolucion/ingestion antes de ejecutar el resto.
2. Ejecuta la matriz de aislamiento de tenants con recursos reales y sus pruebas de regresion.
3. Ejecuta toda la suite backend y los gates frontend (build y cobertura).
4. Crea una base de datos PostgreSQL temporal, aplica todas las migraciones y ejecuta E2E/OCR dentro de la imagen Docker actual. No usa la base de trabajo `docuintel`.
5. Borra solo esa base temporal creada por el propio proceso, salvo que se solicite conservarla.

Una certificacion solo es valida si todas las etapas figuran como `passed` y no se usaron los flags `-SkipFrontend` ni `-SkipDocker`.
