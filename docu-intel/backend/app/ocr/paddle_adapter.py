"""PaddleOCR compatibility adapter (3.5 → 3.7 → future).

This module is the **only** place in the codebase that calls
``PaddleOCR(...)``. The :class:`PaddleOCRAdapter` exposes a single
``run(image_path)`` method that hides four things from the rest of the
codebase:

1. **Lazy model initialisation.** The first ``run()`` call instantiates
   ``PaddleOCR`` under a timeout-aware lock (see
   :func:`paddleocr_init_lock`). Subsequent calls reuse the cached
   instance. Importing this module does **not** load any model.

2. **API version drift.** PaddleOCR 3.x returns a dict with
   ``rec_texts`` / ``rec_scores`` / ``dt_polys``; PaddleOCR 2.x returns
   a nested list of ``[polygon, (text, score)]``; future versions may
   add new shapes (objects with ``.text`` / ``.score`` / ``.polygon``
   attributes). :func:`normalize_paddle_output` accepts every shape
   we have seen shipped by PaddleOCR 2.x-3.x and converts the result
   into the project's :class:`OCRResult` contract.

3. **Predict vs. legacy ocr() routing.** PaddleOCR 3.x ships a
   ``predict()`` method that returns the structured dict natively; the
   legacy ``ocr()`` method is still callable. The adapter picks
   ``predict()`` first when available and falls back to ``ocr()`` if
   ``predict`` is missing or raises. Operators can force either path
   via ``settings.paddle_force_legacy_ocr_api`` /
   ``settings.paddle_force_predict_api``.

4. **Runtime observability.** A single ``logger.info`` call on init
   records the resolved :class:`OcrProfile`, the device, the PaddleOCR
   version and whether the predict API was selected, so an operator
   can confirm the upgrade took effect just by tailing the worker log.

The adapter is intentionally test-friendly: the constructor accepts an
``engine_factory`` callable so unit tests can pass a mock without
importing PaddleOCR at all.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import tempfile
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from app.ocr.base import OCRBlock, OCRResult
from app.ocr.model_registry import OcrProfile, resolve_ocr_models


logger = logging.getLogger("app.ocr.paddle_adapter")


# Maximum time (seconds) the first model load may take before the
# adapter raises instead of blocking the worker thread. Mirrors the
# ``_PADDLE_INIT_TIMEOUT_SECONDS`` constant in the legacy
# :mod:`app.ocr.paddle` module so the adapter behaves identically.
_PADDLE_INIT_TIMEOUT_SECONDS: float = 120.0


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def polygon_to_bbox(polygon: object) -> tuple[float, float, float, float] | None:
    """Axis-aligned bbox of a polygon. Tolerant of garbage inputs.

    Returns ``(x_min, y_min, x_max, y_max)`` for a non-empty iterable
    of ``(x, y)`` points, or ``None`` for empty / malformed input.
    """
    if not isinstance(polygon, (list, tuple)) or not polygon:
        return None
    try:
        xs = [float(point[0]) for point in polygon]
        ys = [float(point[1]) for point in polygon]
    except (IndexError, TypeError, ValueError):
        return None
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------
# Output normalisation (predict / ocr / object / future formats)
# ---------------------------------------------------------------------------


def _coerce_float(value: Any) -> float | None:
    """Return ``value`` as ``float`` or ``None`` when not coercible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _polygon_to_points(polygon: Any) -> list[list[float]]:
    """Coerce a polygon in any of the known formats to ``[[x, y], ...]``."""
    if polygon is None:
        return []
    if hasattr(polygon, "tolist") and callable(polygon.tolist):
        polygon = polygon.tolist()
    if not isinstance(polygon, (list, tuple)):
        return []
    out: list[list[float]] = []
    for point in polygon:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                out.append([float(point[0]), float(point[1])])
            except (TypeError, ValueError):
                continue
        elif isinstance(point, dict) and "x" in point and "y" in point:
            try:
                out.append([float(point["x"]), float(point["y"])])
            except (TypeError, ValueError, KeyError):
                continue
    return out


def _extract_block_from_predict_page(page: Mapping[str, Any]) -> list[tuple[str, float | None, list[list[float]]]]:
    """Convert one PaddleOCR 3.x ``predict`` page dict to internal triples.

    Each triple is ``(text, score, polygon_points)``.
    """
    rec_texts = page.get("rec_texts") or []
    rec_scores = page.get("rec_scores") or []
    dt_polys = page.get("dt_polys") or []
    out: list[tuple[str, float | None, list[list[float]]]] = []
    for index, text in enumerate(rec_texts):
        score = _coerce_float(rec_scores[index]) if index < len(rec_scores) else None
        polygon = _polygon_to_points(dt_polys[index]) if index < len(dt_polys) else []
        out.append((str(text or ""), score, polygon))
    return out


def _extract_block_from_legacy_line(line: Any) -> tuple[str, float | None, list[list[float]]] | None:
    """Convert one PaddleOCR 2.x / nested-list line to internal triple."""
    if isinstance(line, (list, tuple)) and len(line) >= 2:
        polygon_raw = line[0]
        payload = line[1]
        # A real PaddleOCR 2.x line is ``[polygon, (text, score)]`` where the
        # polygon is a list of ``(x, y)`` points. A bare list of numbers at
        # ``line[0]`` is NOT a valid line: it is either a polygon being
        # misinterpreted as a line (when the caller accidentally passed a
        # polygon-list as a "page") or some other shape we do not understand.
        if isinstance(polygon_raw, (list, tuple)) and polygon_raw:
            first = polygon_raw[0]
            if isinstance(first, (list, tuple)):
                # Polygon-list shape: proceed normally.
                polygon = _polygon_to_points(polygon_raw)
            elif isinstance(first, (int, float)):
                # Polygon raw is itself a coordinate pair → ``line`` itself is
                # the polygon, not a [polygon, payload] pair. Bail out.
                return None
            else:
                return None
        else:
            polygon = []
        if isinstance(payload, (list, tuple)) and len(payload) >= 2:
            text = str(payload[0] or "")
            score = _coerce_float(payload[1])
        else:
            text = str(payload)
            score = None
        return text, score, polygon

    # Future-proof: objects with .text / .score / .polygon / .bbox
    text = getattr(line, "text", None)
    score_attr = getattr(line, "score", None)
    polygon = getattr(line, "polygon", None) or getattr(line, "bbox", None)
    if text is not None and score_attr is not None:
        return str(text), _coerce_float(score_attr), _polygon_to_points(polygon)
    return None


def normalize_paddle_output(
    raw: Any,
    *,
    allow_unknown: bool = True,
) -> list[OCRBlock]:
    """Convert any supported PaddleOCR output shape into :class:`OCRBlock`.

    ``raw`` may be:

    * ``None`` → ``[]``.
    * A single page dict (PaddleOCR 3.x ``predict``) → list of blocks.
    * A list/tuple of page dicts → flat list of blocks.
    * A page-level list of lines (PaddleOCR 2.x ``ocr`` / legacy).
    * A nested list of pages → flat list of blocks.
    * A generator / arbitrary iterable → consumed once.

    Unknown shapes return ``[]`` (with a warning) when ``allow_unknown``
    is ``True``; otherwise they raise ``ValueError`` so a regression is
    caught by the future-compatibility tests.
    """
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        raws: list[Any] = [raw]
    elif isinstance(raw, (list, tuple)):
        raws = list(raw)
    elif isinstance(raw, Iterable):
        raws = list(raw)
    else:
        if allow_unknown:
            logger.warning("normalize_paddle_output: unsupported raw type %s", type(raw))
            return []
        raise ValueError(f"Unsupported PaddleOCR output type: {type(raw)!r}")

    blocks: list[OCRBlock] = []
    for page in raws:
        if page is None:
            continue
        if isinstance(page, Mapping):
            for text, score, polygon in _extract_block_from_predict_page(page):
                blocks.append(
                    OCRBlock(
                        text=text,
                        confidence=score,
                        bbox=polygon_to_bbox(polygon) if polygon else None,
                    )
                )
            continue

        if isinstance(page, (list, tuple)):
            for line in page:
                parsed = _extract_block_from_legacy_line(line)
                if parsed is None:
                    continue
                text, score, polygon = parsed
                blocks.append(
                    OCRBlock(
                        text=text,
                        confidence=score,
                        bbox=polygon_to_bbox(polygon) if polygon else None,
                    )
                )
            continue

        parsed = _extract_block_from_legacy_line(page)
        if parsed is not None:
            text, score, polygon = parsed
            blocks.append(
                OCRBlock(
                    text=text,
                    confidence=score,
                    bbox=polygon_to_bbox(polygon) if polygon else None,
                )
            )
            continue

        if allow_unknown:
            logger.warning("normalize_paddle_output: unknown page type %s", type(page))
            continue
        raise ValueError(f"Unsupported PaddleOCR page type: {type(page)!r}")

    return blocks


# ---------------------------------------------------------------------------
# Locking (process-level init serialisation)
# ---------------------------------------------------------------------------


@contextmanager
def paddleocr_init_lock():
    """Cross-process lock that serialises the PaddleOCR first-init.

    The lock is a no-op on Windows because ``fcntl`` is unavailable
    there; the worker-level singleton pattern covers that case.
    """
    is_unix = os.name != "nt"
    if not is_unix:
        with nullcontext():
            yield
        return
    try:
        import fcntl
    except Exception:
        with nullcontext():
            yield
        return
    lock_path = Path(tempfile.gettempdir()) / "docuintel_paddleocr_init.lock"
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)  # type: ignore[attr-defined]
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@dataclass
class _EngineHolder:
    """Lazily-built singleton holding the underlying PaddleOCR instance.

    The actual model is only constructed when ``get()`` is called the
    first time; importing this module never instantiates PaddleOCR.
    """

    profile: OcrProfile
    lang: str
    device: str | None
    engine_factory: Callable[[], Any] | None
    _instance: Any = None
    _failed: bool = False

    def get(self) -> Any:
        if self._instance is not None:
            return self._instance
        if self._failed:
            raise RuntimeError(
                "PaddleOCR model init failed previously; reset the worker to retry."
            )

        def _do_init() -> Any:
            with paddleocr_init_lock():
                if self.engine_factory is not None:
                    return self.engine_factory()
                return self._default_init()

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_do_init)
                self._instance = future.result(timeout=_PADDLE_INIT_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            logger.error(
                "PaddleOCR init timed out after %.0fs (lang=%s, device=%s, profile=%s)",
                _PADDLE_INIT_TIMEOUT_SECONDS,
                self.lang,
                self.device,
                self.profile.id,
            )
            self._failed = True
            raise RuntimeError(
                f"PaddleOCR model init timed out after {_PADDLE_INIT_TIMEOUT_SECONDS}s"
            ) from None
        except Exception:
            self._failed = True
            raise
        return self._instance

    def _default_init(self) -> Any:
        from paddleocr import PaddleOCR

        kwargs: dict[str, Any] = {
            "use_textline_orientation": True,
            "lang": self.lang,
            "enable_mkldnn": False,
        }
        if self.profile.detection_model_name:
            kwargs["det_model_dir"] = self.profile.detection_model_name
        if self.profile.recognition_model_name:
            kwargs["rec_model_dir"] = self.profile.recognition_model_name
        if self.device:
            kwargs["device"] = self.device
        return PaddleOCR(**kwargs)


class PaddleOCRAdapter:
    """Single entry point for running PaddleOCR against one image.

    Constructors are cheap; the expensive PaddleOCR ``__init__`` runs
    only on the first ``run()`` call. The adapter is reusable across
    threads but the underlying PaddleOCR engine is not — workers are
    expected to keep one adapter per worker process.
    """

    def __init__(
        self,
        *,
        profile: OcrProfile | None = None,
        lang: str = "es",
        device: str | None = None,
        engine_factory: Callable[[], Any] | None = None,
        allow_unknown_output: bool = True,
        log_runtime_info: bool = True,
        settings: object | None = None,
    ) -> None:
        self._profile_override = profile
        self.lang = lang
        self.device = device
        self._engine_factory = engine_factory
        self.allow_unknown_output = allow_unknown_output
        self.log_runtime_info = log_runtime_info

        resolved = (
            profile if profile is not None else resolve_ocr_models(settings)
            if settings is not None
            else None
        )
        self.profile: OcrProfile = resolved or _default_profile()
        self._holder = _EngineHolder(
            profile=self.profile,
            lang=lang,
            device=device,
            engine_factory=engine_factory,
        )

    @property
    def name(self) -> str:
        return "paddleocr"

    def _log_runtime_info(self) -> None:
        if not self.log_runtime_info:
            return
        try:
            import paddleocr as _paddleocr_mod  # noqa: F401

            paddle_version = getattr(_paddleocr_mod, "__version__", "unknown")
        except Exception:
            paddle_version = "unavailable"
        has_predict = False
        try:
            engine = self._holder.get()
            has_predict = callable(getattr(engine, "predict", None))
        except Exception as exc:
            logger.warning("paddle_adapter: runtime probe failed: %s", exc)
            engine = None
        logger.info(
            "paddle_adapter ready profile=%s model_type=%s lang=%s device=%s "
            "paddleocr_version=%s predict_api=%s",
            self.profile.id,
            self.profile.model_type,
            self.lang,
            self.device,
            paddle_version,
            has_predict,
        )

    def run(self, image_path: Path) -> OCRResult:
        """Run OCR on a single image file and return the result."""
        try:
            engine = self._holder.get()
        except Exception:
            # Runtime info could not be emitted (init failed). Re-raise.
            raise
        if self.log_runtime_info and not getattr(self, "_logged_runtime", False):
            self._log_runtime_info()
            self._logged_runtime = True

        raw = self._invoke_engine(engine, str(image_path))
        blocks = normalize_paddle_output(raw, allow_unknown=self.allow_unknown_output)
        text = "\n".join(block.text for block in blocks if block.text)
        confidences = [b.confidence for b in blocks if b.confidence is not None]
        average = sum(confidences) / len(confidences) if confidences else None
        return OCRResult(text=text, confidence=average, blocks=blocks, engine=self.name)

    def _invoke_engine(self, engine: Any, path: str) -> Any:
        """Call ``predict`` if available and allowed, else ``ocr``."""
        use_predict = self.profile.use_predict_api
        if use_predict and callable(getattr(engine, "predict", None)):
            try:
                return list(engine.predict(path))
            except Exception as exc:
                logger.warning(
                    "paddle_adapter: predict() failed (%s); falling back to ocr()", exc
                )
        # Legacy / fallback path.
        if callable(getattr(engine, "ocr", None)):
            return engine.ocr(path)
        # Future-proof: the engine doesn't expose either API. Return an
        # empty result so the cascade keeps the primary tier.
        logger.warning(
            "paddle_adapter: engine has neither predict() nor ocr(); returning empty"
        )
        return None


def _default_profile() -> OcrProfile:
    from app.ocr.model_registry import get_ocr_profile

    return get_ocr_profile(None)


__all__ = [
    "PaddleOCRAdapter",
    "normalize_paddle_output",
    "polygon_to_bbox",
    "paddleocr_init_lock",
]