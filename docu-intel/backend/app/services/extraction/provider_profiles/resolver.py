"""Per-supplier provider profiles for structured extraction.

Profiles are YAML files in this directory. Each one describes:

* ``detection``: regexes (case-insensitive) for the supplier tax ID,
  name and a free-form header. The resolver tries every profile
  against the first ~2000 characters of the document text and
  returns the profile with the most matches.
* ``locale``: ``es-ES`` (default) or ``en-US``. Drives
  :func:`app.services.business_extraction._parse_amount`.
* ``header_keywords``: per-field full-word regexes that extend or
  override the defaults in
  :mod:`app.services.extraction.table_extraction`.
* ``field_patterns``: per-field regex overrides used by
  :func:`resolve_field_pattern` for the budget / order / invoice
  number and the total label.

The :func:`resolve_profile` function is the public entry point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

_PROFILE_DIR = Path(__file__).resolve().parent


@dataclass
class ProviderProfile:
    name: str
    display_name: str
    locale: str = "es-ES"
    detection_tax_id: list[re.Pattern[str]] = field(default_factory=list)
    detection_name: list[re.Pattern[str]] = field(default_factory=list)
    detection_header: list[re.Pattern[str]] = field(default_factory=list)
    header_keywords: dict[str, list[re.Pattern[str]]] = field(default_factory=dict)
    field_patterns: dict[str, list[re.Pattern[str]]] = field(default_factory=dict)

    @property
    def is_generic(self) -> bool:
        return self.name == "generico"


def _compile(regexes: Iterable[str]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for raw in regexes or []:
        try:
            compiled.append(re.compile(raw, flags=re.IGNORECASE))
        except re.error:
            # Skip bad patterns so a typo in one profile does not
            # break the whole resolver.
            continue
    return compiled


def _load_yaml(path: Path) -> ProviderProfile:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    detection = data.get("detection", {}) or {}
    return ProviderProfile(
        name=str(data.get("name", path.stem)),
        display_name=str(data.get("display_name", data.get("name", path.stem))),
        locale=str(data.get("locale", "es-ES")),
        detection_tax_id=_compile(detection.get("tax_id", [])),
        detection_name=_compile(detection.get("name", [])),
        detection_header=_compile(detection.get("header", [])),
        header_keywords={
            field_name: _compile(patterns)
            for field_name, patterns in (data.get("header_keywords") or {}).items()
        },
        field_patterns={
            field_name: _compile(patterns)
            for field_name, patterns in (data.get("field_patterns") or {}).items()
        },
    )


def _load_all_profiles() -> dict[str, ProviderProfile]:
    profiles: dict[str, ProviderProfile] = {}
    for path in sorted(_PROFILE_DIR.glob("*.yaml")):
        try:
            profile = _load_yaml(path)
        except Exception:
            # A malformed profile must not break the resolver for the
            # rest of the documents.
            continue
        profiles[profile.name] = profile
    if "generico" not in profiles:
        # Defensive: the generic profile is mandatory. If someone
        # deleted the YAML, re-create an in-memory copy.
        profiles["generico"] = ProviderProfile(
            name="generico",
            display_name="Genérico (es-ES)",
            locale="es-ES",
        )
    return profiles


_PROFILE_CACHE: dict[str, ProviderProfile] | None = None


def _get_profiles() -> dict[str, ProviderProfile]:
    global _PROFILE_CACHE
    if _PROFILE_CACHE is None:
        _PROFILE_CACHE = _load_all_profiles()
    return _PROFILE_CACHE


def reset_cache() -> None:
    """Clear the profile cache. Useful for tests and admin reloads."""
    global _PROFILE_CACHE
    _PROFILE_CACHE = None


def _score_profile(profile: ProviderProfile, sample: str) -> int:
    score = 0
    for pat in profile.detection_tax_id:
        if pat.search(sample):
            score += 3  # tax id is the strongest signal
    for pat in profile.detection_name:
        if pat.search(sample):
            score += 2
    for pat in profile.detection_header:
        if pat.search(sample):
            score += 1
    return score


def resolve_profile(text: str, *, sample_size: int = 2000) -> ProviderProfile:
    """Return the best-matching profile for the given document text.

    The first ``sample_size`` characters are scanned against every
    non-generic profile. The profile with the highest score wins;
    ties resolve alphabetically so the behaviour is deterministic.
    If no profile scores above zero the generic profile is returned.
    """
    sample = (text or "")[:sample_size]
    profiles = _get_profiles()
    best: ProviderProfile | None = None
    best_score = 0
    for profile in profiles.values():
        if profile.is_generic:
            continue
        score = _score_profile(profile, sample)
        if score > best_score or (
            score == best_score and best is not None and profile.name < best.name
        ):
            best = profile
            best_score = score
    if best is None:
        return profiles["generico"]
    return best


def list_profiles() -> list[ProviderProfile]:
    """Return every profile in deterministic order, generic first."""
    profiles = list(_get_profiles().values())
    profiles.sort(key=lambda p: (not p.is_generic, p.name))
    return profiles


def resolve_field_pattern(
    profile: ProviderProfile, field_name: str, fallback: list[str]
) -> list[str]:
    """Return the patterns to try for a field: profile-specific first,
    then the generic fallback. Returns compiled patterns as raw strings
    so callers can use them with :func:`re.search` flags.
    """
    out: list[str] = []
    for pat in profile.field_patterns.get(field_name, []):
        out.append(pat.pattern)
    for raw in fallback:
        if raw not in out:
            out.append(raw)
    return out
