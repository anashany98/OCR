from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger("app.ocr.preprocess")
UPSCALE_MIN_SIDE = 1500

# Cache for preprocessed images within a single cascade run.
# Key: (resolved_input_path, engine_name) → preprocessed output path.
# The cascading OCR clears this before each page so it never grows unbounded.
_preprocess_cache: dict[tuple[str, str], Path] = {}


def clear_preprocess_cache() -> None:
    """Drop cached preprocessed images. Called by the cascading OCR before
    each new page so the dict never leaks across pages."""
    _preprocess_cache.clear()


def preprocess_for_tesseract(path: Path) -> Path:
    """Prepare scanned images for Tesseract.

    Tesseract benefits from aggressive grayscale cleanup and adaptive
    binarization. The original file is never modified; failures return the
    original path after logging.
    """
    try:
        import cv2

        image = cv2.imread(str(path))
        if image is None:
            return path
        image = _correct_orientation(image)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
        denoised = _enhance_contrast(denoised)
        denoised = _sharpen_if_blurry(denoised)
        deskewed = _deskew_gray(denoised)
        scaled = _upscale_if_small(deskewed)
        threshold = cv2.adaptiveThreshold(
            scaled,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11,
        )
        output = _temporary_output_path(path, "tesseract")
        cv2.imwrite(str(output), threshold)
        return output
    except Exception as exc:
        logger.warning("Tesseract preprocess failed for %s: %s", path, exc)
        return path


def preprocess_for_paddle(path: Path) -> Path:
    """Prepare scanned images for PaddleOCR/PP-Structure without binarizing."""
    try:
        import cv2

        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            return path
        image = _correct_orientation(image)
        denoised = cv2.fastNlMeansDenoisingColored(image, None, 4, 4, 7, 21)
        denoised = _enhance_contrast_color(denoised)
        gray = cv2.cvtColor(denoised, cv2.COLOR_BGR2GRAY)
        deskewed = _deskew_color(denoised, gray)
        scaled = _upscale_if_small(deskewed)
        output = _temporary_output_path(path, "paddle")
        cv2.imwrite(str(output), scaled)
        return output
    except Exception as exc:
        logger.warning("Paddle preprocess failed for %s: %s", path, exc)
        return path


def preprocess_for_ocr(path: Path) -> Path:
    """Backward-compatible alias for older parser code."""
    return preprocess_for_tesseract(path)


def _looks_like_scan(gray) -> bool:
    """Detect if the image is a scan (mostly B/W, large empty areas).

    Scans have a bimodal histogram (lots of pixels near 0 or 255,
    few in between) and small laplacian variance. Photos are smoother
    and continuous-tone.
    """
    import cv2
    import numpy as np

    hist = cv2.calcHist([gray], [0], None, [16], [0, 256]).ravel()
    total = hist.sum() or 1
    extreme = hist[0] + hist[-1]
    extreme_ratio = extreme / total
    laplacian = cv2.Laplacian(gray, cv2.CV_64F).var()
    color_var = float(gray.std())
    if extreme_ratio > 0.55 and color_var < 70:
        return True
    if laplacian < 50 and color_var < 60:
        return True
    return False


def preprocess_adaptive(path: Path, *, engine: str) -> Path:
    """Adaptive preprocessor that picks the right pipeline by content type.

    - Scans (mostly B/W): Tesseract gets denoise + deskew + adaptive
      binarization. PaddleOCR gets grayscale + deskew (no binarization,
      which would destroy tabular data and hurt PP-Structure).
    - Photos / continuous-tone (the bulk of the 178 low-quality docs
      from phone cameras): both engines get the manuscript-style path
      that preserves color information and never binarizes.

    Results are cached per (path, engine) within a cascade run so the
    same page is never preprocessed twice when Tesseract → Paddle →
    PP-Structure all need it.
    """
    cache_key = (str(path.resolve()), engine)
    cached = _preprocess_cache.get(cache_key)
    if cached is not None and cached.exists():
        return cached

    try:
        import cv2

        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            return path
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        is_scan = _looks_like_scan(gray)

        if is_scan:
            engine_path = preprocess_for_tesseract(path) if engine == "tesseract" else preprocess_for_paddle(path)
        else:
            engine_path = preprocess_for_manuscript(path)

        _preprocess_cache[cache_key] = engine_path
        return engine_path
    except Exception as exc:
        logger.warning("Adaptive preprocess failed for %s: %s", path, exc)
        return preprocess_for_tesseract(path)


def _temporary_output_path(path: Path, engine: str) -> Path:
    with tempfile.NamedTemporaryFile(
        prefix=f"{path.stem}.{engine}.",
        suffix=".png",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.close()
        return Path(handle.name)


def _correct_orientation(image):
    import cv2

    rotation = _detect_osd_rotation(image)
    if rotation == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if rotation == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if rotation == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image


def _detect_osd_rotation(image) -> int:
    try:
        import cv2
        import pytesseract
        from PIL import Image

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        osd = pytesseract.image_to_osd(Image.fromarray(rgb))
    except Exception as exc:
        logger.debug("Tesseract OSD orientation detection failed: %s", exc)
        return 0

    for line in str(osd).splitlines():
        if line.lower().startswith("rotate:"):
            try:
                value = int(line.split(":", 1)[1].strip())
            except ValueError:
                return 0
            return value if value in {90, 180, 270} else 0
    return 0


def _deskew_gray(gray):
    import cv2

    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    coords = cv2.findNonZero(cv2.bitwise_not(binary))
    if coords is None:
        return gray
    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    if abs(angle) < 0.5:
        return gray
    height, width = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((width // 2, height // 2), angle, 1.0)
    return cv2.warpAffine(
        gray,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _deskew_color(image, gray):
    import cv2

    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    coords = cv2.findNonZero(cv2.bitwise_not(binary))
    if coords is None:
        return image
    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    if abs(angle) < 0.5:
        return image
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width // 2, height // 2), angle, 1.0)
    return cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _upscale_if_small(image):
    import cv2

    height, width = image.shape[:2]
    if min(height, width) >= UPSCALE_MIN_SIDE:
        return image
    return cv2.resize(image, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)


def _enhance_contrast(gray):
    """Apply CLAHE to improve contrast on washed-out scans."""
    import cv2

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _enhance_contrast_color(image):
    """Apply CLAHE to the L channel of LAB color space."""
    import cv2

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)


def _sharpen_if_blurry(gray):
    """Apply unsharp masking if the image appears blurry."""
    import cv2

    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    if laplacian_var < 100:
        blurred = cv2.GaussianBlur(gray, (0, 0), 3)
        return cv2.addWeighted(gray, 1.5, blurred, -0.5, 0)
    return gray


def preprocess_for_manuscript(path: Path) -> Path:
    """Prepare hand-drawn sketches, furniture photos, and fabric samples
    for the VLM (Tier 4). Unlike Tesseract preprocessing, this does NOT
    binarize — the VLM needs color/texture to identify objects and
    associate measurements with them.

    Optimizations:
    - Gentle denoise (preserves pencil/pen strokes)
    - Contrast enhancement (makes handwritten numbers more readable)
    - Upscaling if small (phone photos are often low-res)
    - NO deskew (hand-drawn sketches are intentionally angled)
    - NO binarization (VLM needs visual context)
    """
    try:
        import cv2

        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            return path

        # Gentle denoise — keep pencil strokes, remove sensor noise
        denoised = cv2.fastNlMeansDenoisingColored(image, None, 3, 3, 7, 21)

        # Enhance contrast on the L channel (makes handwriting pop)
        lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        enhanced = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)

        # Upscale phone photos — VLM works better on larger images
        height, width = enhanced.shape[:2]
        if min(height, width) < UPSCALE_MIN_SIDE:
            scale = min(2.0, UPSCALE_MIN_SIDE / min(height, width))
            enhanced = cv2.resize(enhanced, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        output = _temporary_output_path(path, "manuscript")
        cv2.imwrite(str(output), enhanced)
        return output
    except Exception as exc:
        logger.warning("Manuscript preprocess failed for %s: %s", path, exc)
        return path
