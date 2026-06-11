"""Layout-aware extraction utilities for business documents.

This package complements :mod:`app.services.business_extraction` with
positional/structural primitives that the legacy regex-based extractors
do not have access to:

* :mod:`app.services.extraction.table_extraction` clusters OCR blocks
  (one block per OCR line, with a bounding box and a confidence) into
  rows and columns, detects a tabular header, and maps the columns to
  semantic fields (reference, description, quantity, unit, unit_price,
  total_price). Used to extract line items from quotes/orders/invoices
  that have a real tabular layout, where the legacy single-line regex
  fails when the description wraps or columns are not left-aligned.

* :mod:`app.services.extraction.provider_profiles` stores YAML profiles
  per supplier (locale, regexes, column aliases) with a YAML-based
  resolver.
"""
from app.services.extraction.table_extraction import (
    extract_lines_from_pages,
    extract_lines_from_text,
)

__all__ = ["extract_lines_from_pages", "extract_lines_from_text"]
