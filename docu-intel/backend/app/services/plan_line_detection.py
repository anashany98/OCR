"""P4 — Line detection from plan images for snap-to-line support.

When a technician draws a room polygon in the plan viewer, the
vertices should snap to the nearest wall line. This module
detects the prominent lines in a plan image using OpenCV's
HoughLinesP and returns them as a list of line segments that
the frontend can use for snapping.

The detection is **pure** (no ML, no GPU) and adds ~100ms per
page. The results are returned as a list of ``(x1, y1, x2, y2)``
tuples in pixel coordinates.

The module is **fail-safe**: on any error an empty list is
returned so the plan viewer still works without snapping.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("app.services.plan_line_detection")


@dataclass(frozen=True)
class DetectedLine:
    """A single line segment detected in the plan image.

    Attributes:
        x1, y1: start point in pixel coordinates.
        x2, y2: end point in pixel coordinates.
        length_px: length of the line in pixels.
        angle_deg: angle of the line in degrees (0 = horizontal,
            90 = vertical).
    """

    x1: float
    y1: float
    x2: float
    y2: float
    length_px: float
    angle_deg: float


def detect_lines(
    image_path: str | Path,
    *,
    min_line_length: int = 50,
    max_line_gap: int = 10,
    threshold: int = 50,
) -> list[DetectedLine]:
    """Detect prominent lines in a plan image.

    Args:
        image_path: path to the plan image (PNG/JPG).
        min_line_length: minimum line length in pixels.
        max_line_gap: maximum gap between line segments to
            merge them into a single line.
        threshold: HoughLinesP accumulator threshold.

    Returns:
        A list of :class:`DetectedLine`. Empty when no lines
        are detected or on any error.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        logger.debug("OpenCV not available, skipping line detection")
        return []

    try:
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return []

        # Binarize.
        binary = cv2.adaptiveThreshold(
            img,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            15,
            10,
        )

        # Edge detection.
        edges = cv2.Canny(binary, 50, 150, apertureSize=3)

        # HoughLinesP.
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=threshold,
            minLineLength=min_line_length,
            maxLineGap=max_line_gap,
        )

        if lines is None:
            return []

        result: list[DetectedLine] = []
        for line in lines:
            x1, y1, x2, y2 = (
                float(line[0][0]),
                float(line[0][1]),
                float(line[0][2]),
                float(line[0][3]),
            )
            length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            import math

            angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
            result.append(
                DetectedLine(
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    length_px=round(length, 1),
                    angle_deg=round(angle, 1),
                )
            )

        # Sort by length descending (longest walls first).
        result.sort(key=lambda line: line.length_px, reverse=True)
        return result

    except Exception as exc:
        logger.debug("Line detection failed: %s", exc)
        return []


__all__ = [
    "DetectedLine",
    "detect_lines",
]
