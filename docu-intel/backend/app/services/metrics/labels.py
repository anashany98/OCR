"""Label sanitisation helpers for Prometheus metric labels.

Prometheus label values are restricted to Unicode strings. The
two main gotchas are:

- A label that contains a double quote must escape the quote
  with a backslash.
- A label that contains a backslash must escape the backslash
  too (otherwise the backslash ends up escaping the next
  character, which is not what we want).

The original ``metrics.py`` exposed a private ``_label`` helper
that did exactly this. The other escape (CR, LF) is not strictly
required by the OpenMetrics spec but is a common best practice so
multi-line user-controlled strings do not break the exposition
format. We follow that here.
"""

from __future__ import annotations


def escape_label(value: str) -> str:
    """Escape a value so it is safe to embed in a Prometheus label.

    Order matters: backslashes are escaped *first* so the escapes
    we add for ``"`` and newlines are not themselves escaped.
    """
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def metric_key(value: str) -> str:
    """Normalise a free-form string to a stable, URL-safe key.

    Used by the legacy ``get_metrics()`` path that emits
    flat ``key_total`` entries for the admin UI. The Prometheus
    exposition format does not need this; the metric *name* is
    defined in the metric definition.
    """
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_") or "unknown"
