"""O2 — Per-page language detection + adaptive OCR thresholds.

The cascade's escalation rules (``min_chars``, ``min_confidence``) are
document-level constants today. In practice the right value depends
on the language:

* German with umlauts is harder for the LSTM Tesseract model; the
  useful-character density is the same but the per-token confidence
  tends to land lower. A ``min_confidence=0.55`` is more honest than
  ``0.50``.
* CJK languages (Japanese, Chinese, Korean) have very different
  tokenisation: a single character carries more information than a
  Latin letter, so the typical page text length to reach
  "acceptability" is shorter in characters but the confidence
  baseline is lower.
* Spanish / English are the easy cases and the existing defaults
  (0.50) are calibrated for them.

This module centralises:

* the *thresholds* (per-language min_chars / min_confidence);
* the *engine language codes* (the ISO-639 codes Tesseract and
  PaddleOCR expect are *not* always the same as the ISO-639-1 code
  that ``langdetect`` returns);
* the *detection* entry point used by the parser before falling
  back to the cascade, so each scanned page can be OCR'd with the
  right language pack instead of the document-wide default.

The module is **pure** (no I/O) so it can be unit-tested without a
PDF, a database, or a language detection model load beyond the
``langdetect`` import. The PDF parser detects the language per
page using the digital text when present; for scans it inherits
the document's detected language (computed from the first digital
page, or defaulted to ``settings.tesseract_lang``).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Final

logger = logging.getLogger("app.services.ocr_language")


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LanguageThresholds:
    """Per-language escalation thresholds for the OCR cascade.

    Attributes:
        min_chars: minimum number of stripped characters the primary
            engine must produce for the result to be considered
            "acceptable" (i.e. do not escalate to the fallback).
        min_confidence: minimum average token confidence for the
            primary result. Engines report confidence on a 0..1
            scale; values below this trigger escalation.
    """

    min_chars: int
    min_confidence: float


# Conservative defaults that match the existing settings so a
# deployment that never opts into the adaptive logic keeps the same
# behaviour. The original cascade used ``(30, 0.50)``.
DEFAULT_THRESHOLDS: Final[LanguageThresholds] = LanguageThresholds(
    min_chars=30,
    min_confidence=0.50,
)

# Per-language overrides. Languages not listed here use
# ``DEFAULT_THRESHOLDS``. The keys are the ISO-639-1 codes that
# ``langdetect`` returns.
#
# Rationale per language:
# * ``de`` — umlauts (ä, ö, ü, ß) push Tesseract's per-token
#   confidence a few points lower. We accept that and raise the
#   floor so we don't escalate pages that are actually fine.
# * ``fr`` / ``it`` / ``pt`` — accented Latin; behaviour is very
#   close to Spanish/English. Keep the same thresholds.
# * ``ja`` / ``zh`` / ``ko`` — CJK is much denser per character
#   (each glyph carries more meaning) so the typical text length
#   to reach "usefulness" is much shorter; the confidence
#   distribution is also tighter but lower on average.
THRESHOLDS_BY_LANG: Final[dict[str, LanguageThresholds]] = {
    # Western Latin
    "es": LanguageThresholds(min_chars=30, min_confidence=0.50),
    "en": LanguageThresholds(min_chars=30, min_confidence=0.50),
    "pt": LanguageThresholds(min_chars=30, min_confidence=0.50),
    "it": LanguageThresholds(min_chars=30, min_confidence=0.50),
    "fr": LanguageThresholds(min_chars=30, min_confidence=0.50),
    "de": LanguageThresholds(min_chars=30, min_confidence=0.55),
    "nl": LanguageThresholds(min_chars=30, min_confidence=0.50),
    # CJK
    "ja": LanguageThresholds(min_chars=20, min_confidence=0.40),
    "zh": LanguageThresholds(min_chars=20, min_confidence=0.40),
    "ko": LanguageThresholds(min_chars=20, min_confidence=0.40),
    # Cyrillic + Arabic + Devanagari
    "ru": LanguageThresholds(min_chars=30, min_confidence=0.50),
    "ar": LanguageThresholds(min_chars=30, min_confidence=0.50),
    "hi": LanguageThresholds(min_chars=30, min_confidence=0.50),
}


def thresholds_for(language: str | None) -> LanguageThresholds:
    """Return the per-language thresholds, falling back to
    :data:`DEFAULT_THRESHOLDS` when the language is unknown.

    Accepts a ``None`` (no language detected) or a 2-letter ISO code
    that ``langdetect`` would emit. Unknown codes silently fall
    through to the default — this is the right behaviour because
    we'd rather use the conservative thresholds than crash on a
    rare language.
    """
    if not language:
        return DEFAULT_THRESHOLDS
    code = language.lower().strip()
    # Strip region subtags: langdetect returns "zh-cn", "pt-br", etc.
    code = code.split("-")[0].split("_")[0]
    return THRESHOLDS_BY_LANG.get(code, DEFAULT_THRESHOLDS)


# ---------------------------------------------------------------------------
# Engine language-code mapping
# ---------------------------------------------------------------------------
#
# Tesseract uses ISO 639-2 / 3 codes (e.g. ``spa``, ``deu``, ``chi_sim``)
# while PaddleOCR uses ISO 639-1 (e.g. ``es``, ``de``, ``ch``). The
# parser needs the right code per engine, derived from whatever
# language ``langdetect`` returned.
#
# We keep the table small and explicit: the union of languages the
# project actually handles in production, not a full ISO registry.
# Adding a new language = adding a row here + a row in
# ``THRESHOLDS_BY_LANG``.


@dataclass(frozen=True)
class EngineLangCodes:
    """The language codes to pass to each OCR engine for a given
    detected language."""

    tesseract: str
    paddle: str


_LANG_CODES: Final[dict[str, EngineLangCodes]] = {
    "es": EngineLangCodes(tesseract="spa", paddle="es"),
    "en": EngineLangCodes(tesseract="eng", paddle="en"),
    "pt": EngineLangCodes(tesseract="por", paddle="pt"),
    "it": EngineLangCodes(tesseract="ita", paddle="it"),
    "fr": EngineLangCodes(tesseract="fra", paddle="fr"),
    "de": EngineLangCodes(tesseract="deu", paddle="de"),
    "nl": EngineLangCodes(tesseract="nld", paddle="nl"),
    "ja": EngineLangCodes(tesseract="jpn", paddle="japan"),
    "zh": EngineLangCodes(tesseract="chi_sim", paddle="ch"),
    "ko": EngineLangCodes(tesseract="kor", paddle="korean"),
    "ru": EngineLangCodes(tesseract="rus", paddle="ru"),
    "ar": EngineLangCodes(tesseract="ara", paddle="ar"),
    "hi": EngineLangCodes(tesseract="hin", paddle="hi"),
}


# Multi-language packs that Tesseract supports via the ``+`` syntax.
# When a document contains Spanish + English (the common case for
# invoices from international suppliers) we want both packs.
def tesseract_lang_for(language: str | None, *, default: str = "spa+eng") -> str:
    """Return the Tesseract language code for the detected language.

    The ``default`` argument is the project-wide fallback (defaults
    to ``spa+eng`` which matches the existing settings). For a
    detected language that is *not* Spanish or English we use a
    single pack (Tesseract cannot mix CJK with Latin packs in one
    call, so the conservative default is one pack per page).
    """
    if not language:
        return default
    code = language.lower().strip().split("-")[0].split("_")[0]
    entry = _LANG_CODES.get(code)
    if entry is None:
        return default
    return entry.tesseract


def paddle_lang_for(language: str | None, *, default: str = "es") -> str:
    """Return the PaddleOCR language code for the detected language."""
    if not language:
        return default
    code = language.lower().strip().split("-")[0].split("_")[0]
    entry = _LANG_CODES.get(code)
    if entry is None:
        return default
    return entry.paddle


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


# ``langdetect`` is non-deterministic by default; we seed the factory
# the first time we use it so the same input text always maps to the
# same detected language within a process. Imported lazily so the
# rest of the module stays importable in environments where
# ``langdetect`` is not installed (CI smoke tests).
_FACTORY_SEEDED = False


def _ensure_factory_seeded() -> None:
    global _FACTORY_SEEDED
    if _FACTORY_SEEDED:
        return
    try:
        from langdetect import DetectorFactory  # type: ignore

        DetectorFactory.seed = 0
        _FACTORY_SEEDED = True
    except ImportError:  # pragma: no cover
        pass


# Heuristic overrides for short, domain-specific text where
# ``langdetect`` is unreliable. A page that is mostly a number
# sequence ("1234 5678 9012 3456") or a single word should not be
# classified; we return ``None`` so the caller falls back to the
# document-level default.
_CJK_HINT_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
_CYRILLIC_HINT_RE = re.compile(r"[\u0400-\u04ff]")
_ARABIC_HINT_RE = re.compile(r"[\u0600-\u06ff]")
_DEVANAGARI_HINT_RE = re.compile(r"[\u0900-\u097f]")


def _script_hint(text: str) -> str | None:
    """Cheap Unicode-block sniff that catches CJK / Cyrillic / Arabic
    / Devanagari without paying for ``langdetect``. Catches
    languages the model handles poorly on short inputs."""
    if not text:
        return None
    if _CJK_HINT_RE.search(text):
        # Distinguish Japanese kana from Chinese hanzi. Japanese
        # text almost always contains hiragana or katakana; Chinese
        # text contains only hanzi. Korean is the third CJK family
        # and is rare in our doc set, so we default to ``ja`` for
        # mixed CJK and let langdetect correct on the long text.
        if re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text):
            return "ja"
        return "zh"
    if _CYRILLIC_HINT_RE.search(text):
        return "ru"
    if _ARABIC_HINT_RE.search(text):
        return "ar"
    if _DEVANAGARI_HINT_RE.search(text):
        return "hi"
    return None


def detect_language(text: str, *, min_chars: int = 40) -> str | None:
    """Return the ISO-639-1 code of the dominant language in ``text``.

    The function is fail-safe: it returns ``None`` when the text is
    too short to be classified reliably, when the input is empty,
    or when ``langdetect`` is not installed. Callers are expected
    to fall back to the document-level default language in that
    case.

    The Unicode-block sniff runs *before* ``langdetect`` because the
    detector is unreliable on short CJK / RTL inputs (it tends to
    misclassify them as English or Vietnamese).
    """
    if not text or not text.strip():
        return None
    # Short inputs (< 40 chars) are unreliable; only the script hint
    # is consulted.
    stripped = text.strip()
    if len(stripped) < min_chars:
        return _script_hint(stripped)

    script = _script_hint(stripped)
    if script is not None:
        return script

    try:
        _ensure_factory_seeded()
        from langdetect import detect_langs  # type: ignore
    except ImportError:  # pragma: no cover
        return None

    try:
        candidates = detect_langs(stripped)
    except Exception:  # pragma: no cover - langdetect raises LangDetectException
        return None

    if not candidates:
        return None
    top = candidates[0]
    code = (top.lang or "").lower().split("-")[0].split("_")[0]
    return code or None


# ---------------------------------------------------------------------------
# Public bundle: convenience for the PDF parser
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LanguageProfile:
    """The full per-page language package the parser needs:

    * the detected ISO-639-1 code (or ``None`` when not detected),
    * the per-language cascade thresholds,
    * the Tesseract language code,
    * the PaddleOCR language code.
    """

    detected: str | None
    thresholds: LanguageThresholds
    tesseract_lang: str
    paddle_lang: str

    @classmethod
    def for_text(
        cls,
        text: str,
        *,
        default_tesseract_lang: str = "spa+eng",
        default_paddle_lang: str = "es",
    ) -> LanguageProfile:
        code = detect_language(text)
        return cls(
            detected=code,
            thresholds=thresholds_for(code),
            tesseract_lang=tesseract_lang_for(code, default=default_tesseract_lang),
            paddle_lang=paddle_lang_for(code, default=default_paddle_lang),
        )


__all__ = [
    "LanguageThresholds",
    "DEFAULT_THRESHOLDS",
    "THRESHOLDS_BY_LANG",
    "EngineLangCodes",
    "LanguageProfile",
    "thresholds_for",
    "tesseract_lang_for",
    "paddle_lang_for",
    "detect_language",
]
