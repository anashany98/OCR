"""Visual content classifier for image routing.

Uses OpenCV-based heuristics to classify images into categories before OCR.
No external models needed - works with just OpenCV which is already installed.

NOTE: This module is named clip_classifier historically but does NOT use CLIP.
It uses OpenCV heuristics (color variance, edge structure, text detection).

Legacy categories (single-label):
- document: invoices, receipts, scanned documents, forms
- product_photo: furniture, fabric samples, interior design
- plan: architectural plans, technical drawings
- text_document: text-heavy images that need OCR

Phase 5: Multi-label taxonomy via classify_image_multilabel().
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("app.parsers.clip_classifier")

# Minimum image size (pixels on the shorter side) for classification to
# be trusted. Below this, the image is too small for the heuristic
# features (contours, edge density, text-block detection) to be
# meaningful — a 1×1 white pixel or a tiny thumbnail would otherwise
# produce arbitrary scores and could be misclassified as a photo,
# skipping OCR on a valid (if small) document.
_MIN_SIDE = 64


def classify_image(image_path: Path) -> dict:
    """Classify an image using visual heuristics.

    Returns:
        {
            "category": "document" | "product_photo" | "plan" | "text_document" | "unknown",
            "confidence": 0.0-1.0,
            "scores": {"document": 0.x, "product_photo": 0.x, ...}
        }
    """
    try:
        import cv2
        import numpy as np

        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            return {"category": "unknown", "confidence": 0.0, "scores": {}}

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        # Fail open: tiny images are never classified as photos. The
        # heuristics below are not robust on small/thumbnail inputs and
        # a false "photo" verdict would silently skip OCR on a document.
        if min(h, w) < _MIN_SIDE:
            return {"category": "unknown", "confidence": 0.0, "scores": {}}
        total_pixels = h * w

        # Feature 1: Color variance
        # Photos have high color variance, documents have low
        color_var = float(gray.std())

        # Feature 2: Edge structure
        # Documents have strong horizontal/vertical edges (text lines, borders)
        # Photos have organic, scattered edges
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(edges.sum()) / (total_pixels * 255)

        # Count horizontal vs vertical edges
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
        horizontal = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, horizontal_kernel)
        vertical = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, vertical_kernel)
        h_lines = float(horizontal.sum()) / (total_pixels * 255)
        v_lines = float(vertical.sum()) / (total_pixels * 255)

        # Feature 3: Text-like regions
        # Documents have many small, regular text blocks
        # Use adaptive threshold to find text regions
        thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY_INV, 11, 2)
        # Dilate to connect text characters into blocks
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
        dilated = cv2.dilate(thresh, kernel, iterations=1)
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Count text-like blocks (small, rectangular, high aspect ratio)
        text_blocks = 0
        for c in contours:
            area = cv2.contourArea(c)
            if area < 100:  # Too small
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            aspect = bw / max(bh, 1)
            if 0.1 < aspect < 10 and area < total_pixels * 0.01:  # Text-like
                text_blocks += 1

        text_density = text_blocks / max(total_pixels / 10000, 1)

        # Feature 4: Color channels
        # Photos have balanced color channels, documents are mostly gray/white
        b, g, r = cv2.split(image)
        color_balance = float(min(b.std(), g.std(), r.std())) / max(float(max(b.std(), g.std(), r.std())), 1)

        # Feature 5: Contour regularity
        # Documents have more rectangular contours, photos have irregular ones
        all_contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if all_contours:
            areas = [cv2.contourArea(c) for c in all_contours]
            aspect_ratios = []
            for c in all_contours:
                x, y, bw, bh = cv2.boundingRect(c)
                aspect_ratios.append(bw / max(bh, 1))
            avg_aspect = np.mean(aspect_ratios) if aspect_ratios else 1.0
            area_variance = np.var(areas) if len(areas) > 1 else 0
        else:
            avg_aspect = 1.0
            area_variance = 0

        # Classification logic
        scores = {}

        # Document score: low color variance + many text blocks + regular edges
        doc_score = 0.0
        if color_var < 60:
            doc_score += 0.3
        if text_density > 0.5:
            doc_score += 0.3
        if h_lines > 0.01 or v_lines > 0.01:
            doc_score += 0.2
        if color_balance > 0.5:  # Gray-ish
            doc_score += 0.2
        scores["document"] = min(doc_score, 1.0)

        # Product photo score: high color variance + irregular contours + no text
        photo_score = 0.0
        if color_var > 50:
            photo_score += 0.3
        if text_density < 0.3:
            photo_score += 0.3
        if area_variance > 100000:  # Irregular contour sizes
            photo_score += 0.2
        if color_balance < 0.7:  # Colorful
            photo_score += 0.2
        scores["product_photo"] = min(photo_score, 1.0)

        # Plan score: high edge density + structured layout
        plan_score = 0.0
        if edge_density > 0.05:
            plan_score += 0.3
        if h_lines > 0.02 and v_lines > 0.02:  # Grid-like
            plan_score += 0.3
        if text_density > 0.3:
            plan_score += 0.2
        if avg_aspect > 0.5 and avg_aspect < 2.0:  # Regular shapes
            plan_score += 0.2
        scores["plan"] = min(plan_score, 1.0)

        # Text document: mostly text, low color
        text_score = 0.0
        if text_density > 1.0:
            text_score += 0.4
        if color_var < 40:
            text_score += 0.3
        if h_lines > 0.01:
            text_score += 0.3
        scores["text_document"] = min(text_score, 1.0)

        # Pick the winner
        best_category = max(scores, key=scores.get)
        best_score = scores[best_category]

        # If no category scores above threshold, return unknown
        if best_score < 0.3:
            return {"category": "unknown", "confidence": best_score, "scores": scores}

        return {
            "category": best_category,
            "confidence": best_score,
            "scores": scores
        }

    except Exception as exc:
        logger.warning("Image classification failed for %s: %s", image_path.name, exc)
        return {"category": "unknown", "confidence": 0.0, "scores": {}}


__all__ = ["classify_image", "classify_image_multilabel"]


def classify_image_multilabel(image_path: Path) -> dict:
    """Phase 5: Multi-label classification using OpenCV heuristics.

    Returns:
        {
            "labels": [("label", confidence), ...],
            "primary_label": "label",
            "primary_confidence": 0.x,
            "opencv_category": "document" | "product_photo" | ...,
            "opencv_confidence": 0.x,
            "all_scores": {...},
        }
    """
    from app.parsers.image_taxonomy import ImageLabel, classify_by_filename

    # Run legacy classifier
    legacy = classify_image(image_path)

    # Map legacy categories to taxonomy labels
    LEGACY_MAP = {
        "document": [
            (ImageLabel.DOCUMENTO_FOTOGRAFIADO, 0.6),
            (ImageLabel.COMPROBANTE_PAGO, 0.4),
        ],
        "product_photo": [
            (ImageLabel.FOTO_PRODUCTO, 0.6),
            (ImageLabel.FOTO_INSTALACION, 0.3),
        ],
        "plan": [
            (ImageLabel.PLANO_TECNICO, 0.6),
            (ImageLabel.CROQUIS_MEDICION, 0.3),
        ],
        "text_document": [
            (ImageLabel.DOCUMENTO_FOTOGRAFIADO, 0.5),
        ],
        "unknown": [
            (ImageLabel.DESCONOCIDO, 0.2),
        ],
    }

    # Start with filename-based labels
    filename_labels = classify_by_filename(image_path.name)

    # Add OpenCV-based labels
    opencv_labels = LEGACY_MAP.get(legacy["category"], [(ImageLabel.DESCONOCIDO, 0.2)])

    # Merge: take the higher confidence for each label
    all_labels: dict[str, float] = {}
    for label, conf in filename_labels:
        key = label.value if hasattr(label, "value") else str(label)
        all_labels[key] = max(all_labels.get(key, 0), conf)
    for label, conf in opencv_labels:
        key = label.value if hasattr(label, "value") else str(label)
        # Boost OpenCV confidence since it analyzed the actual pixels
        boosted_conf = min(conf + 0.1, 0.95)
        all_labels[key] = max(all_labels.get(key, 0), boosted_conf)

    # Sort by confidence
    sorted_labels = sorted(all_labels.items(), key=lambda x: x[1], reverse=True)
    primary = sorted_labels[0] if sorted_labels else ("desconocido", 0.0)

    return {
        "labels": sorted_labels,
        "primary_label": primary[0],
        "primary_confidence": primary[1],
        "opencv_category": legacy["category"],
        "opencv_confidence": legacy["confidence"],
        "all_scores": legacy.get("scores", {}),
    }
