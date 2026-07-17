"""Template loader for Hyper-Extract.

Templates are small YAML files (one per ``document_type``) that drive the
extraction prompt: they list the fields we want to populate, the entities
we want to surface and any helpful system-prompt guidance for the LLM.

The loader is deliberately defensive: a malformed template must not
break the rest of the pipeline. When a template fails to load we log a
warning and the service falls back to a generic prompt that still
returns valid JSON.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


@dataclass
class HyperExtractTemplate:
    """A parsed ``*.yaml`` template file.

    The dataclass carries the raw payload (``raw``) so a future schema
    migration does not require touching every consumer — callers can
    read either the typed helpers (``fields``, ``entities``,
    ``relations``) or the original dict.
    """

    name: str
    document_type: str
    description: str
    version: int
    system_prompt: str
    fields: list[dict] = field(default_factory=list)
    entities: list[dict] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def _load_yaml(path: Path) -> HyperExtractTemplate | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as exc:
        logger.warning(
            "hyperextract: failed to parse template %s: %s",
            path.name,
            exc,
        )
        return None
    if not isinstance(data, dict):
        logger.warning("hyperextract: template %s is not a mapping, ignoring", path.name)
        return None
    document_type = str(data.get("document_type") or path.stem).strip().lower()
    return HyperExtractTemplate(
        name=path.stem,
        document_type=document_type,
        description=str(data.get("description") or ""),
        version=int(data.get("version") or 1),
        system_prompt=str(data.get("system_prompt") or ""),
        fields=list(data.get("fields") or []),
        entities=list(data.get("entities") or []),
        relations=list(data.get("relations") or []),
        raw=data,
    )


_TEMPLATE_CACHE: dict[str, HyperExtractTemplate] | None = None


def _load_all() -> dict[str, HyperExtractTemplate]:
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is not None:
        return _TEMPLATE_CACHE
    cache: dict[str, HyperExtractTemplate] = {}
    if _TEMPLATE_DIR.is_dir():
        for path in sorted(_TEMPLATE_DIR.glob("*.yaml")):
            template = _load_yaml(path)
            if template is None:
                continue
            cache[template.document_type] = template
    _TEMPLATE_CACHE = cache
    return cache


def reset_cache() -> None:
    """Drop the in-process cache. Tests and the admin reload use this."""
    global _TEMPLATE_CACHE
    _TEMPLATE_CACHE = None


def list_templates() -> list[HyperExtractTemplate]:
    """Return every loaded template, alphabetically by ``document_type``."""
    return sorted(_load_all().values(), key=lambda t: t.document_type)


def load_template(document_type: str | None) -> HyperExtractTemplate | None:
    """Look up a template by ``document_type``.

    Returns ``None`` when no template matches; the caller is then
    expected to fall back to a generic extraction (no template-specific
    system prompt, no field list).
    """
    if not document_type:
        return None
    return _load_all().get(str(document_type).strip().lower())


def build_field_instructions(template: HyperExtractTemplate | None) -> str:
    """Format a template's field list as a compact prompt instruction.

    The output is human-readable Spanish and lists every field with its
    type. When no template is supplied we return an empty string so the
    caller can fall back to a generic prompt.
    """
    if template is None or not template.fields:
        return ""
    lines: list[str] = []
    for entry in template.fields:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        ftype = str(entry.get("type") or "string").strip()
        desc = str(entry.get("description") or "").strip()
        required = bool(entry.get("required"))
        bullet = f"- {name} ({ftype})"
        if required:
            bullet += " [obligatorio]"
        if desc:
            bullet += f": {desc}"
        lines.append(bullet)
    if not lines:
        return ""
    return "Campos a extraer:\n" + "\n".join(lines)
