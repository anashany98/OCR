from __future__ import annotations

import logging
import tempfile
from pathlib import Path


logger = logging.getLogger("app.ocr.preprocess")
UPSCALE_MIN_SIDE = 1500


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


def _temporary_output_path(path: Path, engine: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        prefix=f"{path.stem}.{engine}.",
        suffix=".png",
        dir=path.parent,
        delete=False,
    )
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
