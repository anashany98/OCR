from __future__ import annotations

from pathlib import Path


def preprocess_for_ocr(path: Path) -> Path:
    try:
        import cv2

        image = cv2.imread(str(path))
        if image is None:
            return path
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
        threshold = cv2.adaptiveThreshold(
            denoised,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11,
        )
        output = path.with_name(f"{path.stem}.ocr.png")
        cv2.imwrite(str(output), threshold)
        return output
    except Exception:
        return path

