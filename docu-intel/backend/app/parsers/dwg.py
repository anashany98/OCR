"""Safe DWG -> DXF conversion before technical-plan extraction.

DWG is a binary Autodesk format and must never be sent through the plain-text
parser.  ODA File Converter is intentionally an optional operational
dependency: it is installed and licensed by the deployment owner, while this
module owns the short-lived conversion workspace and feeds its DXF output into
the existing audited DXF parser.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

import httpx

from app.core.config import settings
from app.parsers.dxf import parse_dxf
from app.parsers.types import ExtractedDocument

logger = logging.getLogger("app.parsers.dwg")


class DwgConversionError(ValueError):
    """A DWG could not be converted safely into a DXF plan."""


def _converter_path() -> str:
    configured = settings.dwg_converter_path.strip()
    if configured:
        candidate = Path(configured)
        if candidate.is_file():
            return str(candidate)
        raise DwgConversionError(
            "El conversor DWG configurado no existe o no es un archivo ejecutable."
        )

    discovered = shutil.which("ODAFileConverter")
    if discovered:
        return discovered
    raise DwgConversionError(
        "No hay conversor DWG instalado. Configure DWG_CONVERTER_PATH con ODA File Converter "
        "o convierta el plano a DXF/PDF para procesarlo."
    )


def _convert_dwg_to_dxf(source: Path, destination: Path) -> None:
    """Run ODA File Converter in a private temporary directory.

    ODA receives folder paths rather than a direct output filename.  The
    conversion folder contains only a copied input, so the original upload is
    never modified even when ODA's audit option repairs recoverable defects.
    """
    if settings.dwg_converter_bridge_url.strip():
        _convert_through_windows_bridge(source, destination)
        return

    executable = _converter_path()
    with tempfile.TemporaryDirectory(prefix="docu_intel_dwg_") as temp_dir:
        workspace = Path(temp_dir)
        input_dir = workspace / "input"
        output_dir = workspace / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        copied_input = input_dir / source.name
        shutil.copy2(source, copied_input)
        command = [
            executable,
            str(input_dir),
            str(output_dir),
            settings.dwg_converter_version,
            "DXF",
            "0",  # do not recurse outside this private folder
            "1",  # audit only the copied input
            copied_input.name,
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=settings.dwg_converter_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DwgConversionError(
                "La conversión DWG superó el tiempo máximo permitido."
            ) from exc
        except OSError as exc:
            raise DwgConversionError("No se pudo iniciar el conversor DWG configurado.") from exc

        generated = next(output_dir.rglob("*.dxf"), None)
        if completed.returncode != 0 or generated is None:
            detail = (completed.stderr or completed.stdout or "sin detalle del conversor").strip()
            logger.warning("DWG conversion failed for %s: %s", source.name, detail[:500])
            raise DwgConversionError("No se pudo convertir el plano DWG a DXF de forma segura.")
        shutil.copy2(generated, destination)


def _convert_through_windows_bridge(source: Path, destination: Path) -> None:
    """Convert through the localhost-only Windows ODA bridge.

    Docker Desktop Linux containers cannot execute ``ODAFileConverter.exe``.
    The bridge keeps the executable on the host, receives one temporary copy
    over the Docker host gateway, and returns only the generated DXF.
    """
    base_url = settings.dwg_converter_bridge_url.rstrip("/")
    token = settings.dwg_converter_bridge_token.strip()
    if not token:
        raise DwgConversionError("El puente ODA está configurado sin DWG_CONVERTER_BRIDGE_TOKEN.")

    try:
        with source.open("rb") as handle:
            response = httpx.post(
                f"{base_url}/convert",
                files={"file": (source.name, handle, "application/acad")},
                headers={"X-Docu-Intel-Bridge-Token": token},
                timeout=settings.dwg_converter_timeout_seconds,
            )
    except httpx.TimeoutException as exc:
        raise DwgConversionError("El puente ODA agotó el tiempo máximo de conversión.") from exc
    except httpx.HTTPError as exc:
        raise DwgConversionError("No se pudo contactar con el puente ODA de Windows.") from exc

    if response.status_code != 200:
        detail = response.text.strip()[:300]
        logger.warning("DWG bridge conversion failed for %s: %s", source.name, detail)
        raise DwgConversionError(
            "El puente ODA no pudo convertir el plano DWG a DXF. "
            "Configure DWG_CONVERTER_PATH o revise el puente ODA."
        )
    if not response.content:
        raise DwgConversionError("El puente ODA devolvió un DXF vacío.")
    destination.write_bytes(response.content)


def parse_dwg(path: Path, output_dir: Path) -> ExtractedDocument:
    if path.suffix.lower() != ".dwg":
        raise DwgConversionError("El parser DWG recibió un archivo que no es .dwg.")

    with tempfile.TemporaryDirectory(prefix="docu_intel_dwg_dxf_") as temp_dir:
        converted = Path(temp_dir) / f"{path.stem}.dxf"
        _convert_dwg_to_dxf(path, converted)
        extracted = parse_dxf(converted, output_dir)
        if extracted.cad is not None:
            extracted.cad = replace(
                extracted.cad,
                metadata=replace(
                    extracted.cad.metadata,
                    source_format="dwg",
                    converter="oda_bridge"
                    if settings.dwg_converter_bridge_url.strip()
                    else "oda_file_converter",
                    converter_version=settings.dwg_converter_version,
                ),
            )
        return extracted
