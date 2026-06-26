"""Hyper-Extract — optional structured-extraction layer on top of OCR.

Public surface (re-exported here so callers can ``from
app.services.hyperextract import HyperExtractService``):

* :class:`HyperExtractService` — main entry point.
* :class:`HyperExtractResult` — typed output envelope.
* :class:`HyperExtractTemplate` / :func:`load_template` /
  :func:`list_templates` — template resolution.
"""

from app.services.hyperextract.service import (
    HyperExtractResult,
    HyperExtractService,
)
from app.services.hyperextract.templates import (
    HyperExtractTemplate,
    list_templates,
    load_template,
)

__all__ = [
    "HyperExtractResult",
    "HyperExtractService",
    "HyperExtractTemplate",
    "list_templates",
    "load_template",
]
