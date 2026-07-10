"""FASE 4: VLM-based table extraction for budgets/invoices.

When PP-Structure produces garbage tables (no numeric prices) and the
regex fallback also fails, we send the table image to a vision LLM
(qwen3-vl-8b-instruct) with a structured prompt that returns JSON
with line items. This is the last-resort extractor for hard tables.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
from pathlib import Path

import httpx

from app.core.config import settings
from app.services.business_extraction import ExtractedLine
from app.services.circuit_breaker import CircuitBreaker, CircuitBreakerOpen

logger = logging.getLogger("app.services.vlm_table_extraction")

# Circuit breaker for VLM table calls
_vlm_table_breaker: CircuitBreaker | None = None
_vlm_table_breaker_lock = threading.Lock()


def _get_vlm_table_breaker() -> CircuitBreaker:
    global _vlm_table_breaker
    if _vlm_table_breaker is not None:
        return _vlm_table_breaker
    with _vlm_table_breaker_lock:
        if _vlm_table_breaker is None:
            _vlm_table_breaker = CircuitBreaker(
                fail_max=3,
                reset_timeout=120,
                name="vlm_table",
            )
    return _vlm_table_breaker


TABLE_EXTRACTION_PROMPT = """\
Eres un experto en extracción de datos de presupuestos, facturas y albaranes.

Analiza la imagen de esta tabla y extrae TODAS las líneas con productos/servicios.

Responde EXCLUSIVAMENTE con un JSON válido (sin texto adicional, sin markdown, sin ```).

Formato del JSON:
{
  "lineas": [
    {
      "ref": "código o referencia del producto (string o null)",
      "desc": "descripción del producto/servicio (string)",
      "cant": cantidad numérica (number o null),
      "unidad": "ud", "m", "kg", etc. (string o null),
      "p_unitario": precio unitario numérico (number o null),
      "total": precio total de la línea numérico (number o null)
    }
  ],
  "total_documento": total del documento si es visible (number o null)
}

Reglas:
- Incluye TODAS las líneas visibles, incluso si algunos campos no se pueden leer
- Si un campo no es legible, pon null (no inventes valores)
- Los precios pueden usar coma o punto como decimal (1.234,56 o 1234.56)
- No incluyas filas de encabezado ni separadores
- Si la imagen no contiene una tabla de presupuesto/factura, devuelve {"lineas": [], "total_documento": null}
"""


def vlm_tabla_a_json(
    image_path: Path,
    *,
    timeout_seconds: float | None = None,
) -> list[ExtractedLine] | None:
    """Send a table image to the vision LLM and parse the JSON response.

    Returns a list of :class:`ExtractedLine` on success, or ``None``
    when the VLM call fails or returns unparseable output.
    """
    if not settings.enable_dots_mocr:
        return None

    timeout = timeout_seconds or settings.vision_timeout_seconds
    model = settings.vision_model
    base_url = (settings.ai_base_url or "").rstrip("/")

    if not base_url or not model:
        logger.debug("VLM table extraction: no endpoint configured")
        return None

    # Read and encode image
    try:
        image_bytes = image_path.read_bytes()
    except OSError as exc:
        logger.warning("VLM table: cannot read image %s: %s", image_path, exc)
        return None

    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    suffix = image_path.suffix.lower().lstrip(".") or "png"
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "tif": "tiff",
            "tiff": "tiff", "bmp": "bmp", "webp": "webp"}.get(suffix, "png")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": TABLE_EXTRACTION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/{mime};base64,{image_b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 4000,
        "temperature": 0.0,
    }

    breaker = _get_vlm_table_breaker()
    try:
        with breaker:
            resp = httpx.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=timeout,
            )
            resp.raise_for_status()
    except CircuitBreakerOpen:
        logger.warning("VLM table: circuit breaker open, skipping")
        return None
    except Exception as exc:
        logger.warning("VLM table extraction failed: %s", exc)
        return None

    # Parse response
    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        logger.warning("VLM table: bad response format: %s", exc)
        return None

    return _parse_vlm_json(content)


def _parse_vlm_json(content: str) -> list[ExtractedLine] | None:
    """Parse the VLM's JSON response into ExtractedLine objects."""
    # Strip markdown code fences if present
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Try to find JSON in the response
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                logger.debug("VLM table: could not parse JSON from response")
                return None
        else:
            logger.debug("VLM table: no JSON found in response")
            return None

    raw_lines = data.get("lineas") or data.get("lines") or []
    if not raw_lines:
        return []

    lines: list[ExtractedLine] = []
    for item in raw_lines:
        if not isinstance(item, dict):
            continue
        desc = (
            item.get("desc")
            or item.get("description")
            or item.get("descripcion")
            or item.get("concepto")
        )
        if not desc:
            continue
        lines.append(
            ExtractedLine(
                reference=(
                    item.get("ref")
                    or item.get("reference")
                    or item.get("referencia")
                ),
                description=str(desc),
                quantity=_to_float(
                    item.get("cant")
                    or item.get("quantity")
                    or item.get("unidades")
                    or item.get("qty")
                ),
                unit=item.get("unidad") or item.get("unit"),
                unit_price=_to_float(
                    item.get("p_unitario")
                    or item.get("unit_price")
                    or item.get("precio_unitario")
                    or item.get("precio")
                ),
                total_price=_to_float(
                    item.get("total")
                    or item.get("total_price")
                    or item.get("precio_total")
                    or item.get("importe")
                ),
                confidence=0.85,
            )
        )
    return lines if lines else None


def _to_float(value) -> float | None:
    """Safely convert a value to float, handling Spanish number formats."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    # Handle Spanish format: 1.234,56 → 1234.56
    s = s.replace("€", "").replace("$", "").replace("£", "").strip()
    if "," in s and "." in s:
        if s.rindex(",") > s.rindex("."):
            # 1.234,56 → remove dots, replace comma with dot
            s = s.replace(".", "").replace(",", ".")
        else:
            # 1,234.56 → remove commas
            s = s.replace(",", "")
    elif "," in s:
        # Could be 1234,56 (decimal) or 1,234 (thousands)
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None
