# Structured Extraction — Operators' Guide

This module replaces the legacy 100%-regex business extractor with a
two-layer pipeline:

1. **Layout-aware clustering** of OCR blocks for line items, which
   handles real invoices where the description wraps, columns drift
   and the unit is sometimes glued to the price.
2. **Per-supplier provider profiles** (YAML) that pin the locale, the
   field regexes and the column aliases for known suppliers. Unknown
   suppliers fall back to a generic Spanish (``es-ES``) profile.

The legacy regex is preserved as a fallback. Every public function
keeps the same signature, with optional ``pages`` /
``locale`` parameters appended.

## File map

```
app/services/business_extraction.py
  Public extract_* / persist_* functions, _status / _parse_amount
  / _find_related_*_id / _validate_extraction helpers.

app/services/extraction/
  __init__.py                    — public API re-exports
  table_extraction.py            — layout-aware line extraction
  provider_profiles/
    generico.yaml                — fallback profile (es-ES)
    herrajes_centro.yaml         — test-fixture supplier (es-ES)
    talleres_norte.yaml          — test-fixture supplier (en-US)
    resolver.py                  — YAML loader + provider matcher
```

## Adding a new supplier profile

1. Create ``app/services/extraction/provider_profiles/<supplier>.yaml``.
2. Fill in the detection signals. The resolver scores every
   non-generic profile against the first ~2 000 characters of the
   document text. The profile with the highest score wins; ties
   resolve alphabetically.

```yaml
name: acme_sl
display_name: Acme SL (es-ES)
locale: es-ES

detection:
  tax_id:
    - "\\bB12345678\\b"
  name:
    - "\\bacme\\b"
  header: []

# Optional: per-field full-word regexes for the table header.
header_keywords:
  reference:
    - "\\bref\\b"
  description:
    - "\\bdescripci[oó]n\\b"
  quantity:
    - "\\bcant\\b"
  unit_price:
    - "\\bprecio\\b"
  total_price:
    - "\\btotal\\b"

# Optional: regex overrides for the document-number / total-label
# fields. The resolver merges these with the generic profile's
# patterns and dedupes them.
field_patterns: {}
```

3. Reload the resolver cache (no restart needed) by calling
   ``app.services.extraction.provider_profiles.reset_cache()`` from
   any admin endpoint, or simply restart the worker.

## Validation & coherence

Every extraction now goes through ``_validate_extraction`` which
checks:

* **Per line:** ``quantity × unit_price ≈ total_price`` (abs
  tolerance 0.05, rel 2 %).
* **Subtotal:** ``Σ(line.total_price) ≈ total_amount`` (abs
  tolerance 0.50, rel 1 %).
* **Invoice:** ``taxable_base + vat_amount ≈ total_amount`` (abs
  tolerance 0.05).

Failures are returned as :class:`ValidationIssue` objects on
``PersistedBusinessExtraction.validation_issues`` and as short
human-readable strings on ``PersistedBusinessExtraction.review_reasons``
so the admin UI can show *why* a document needs human review instead
of a bare ``needs_review`` flag.

## Locale handling

``_parse_amount(value, locale="es-ES")`` is the single entry point
for amount parsing. The locale argument drives the
decimal/thousands separator rule. The provider profile resolver
returns the right locale per supplier (defaults to ``es-ES``).

Tests cover the four common cases:

* ``es-ES`` thousands + decimal: ``"1.234,56"`` → ``1234.56``
* ``es-ES`` decimal only: ``"3,5"`` → ``3.5``
* ``en-US`` thousands + decimal: ``"1,234.56"`` → ``1234.56``
* ``en-US`` decimal only: ``"12.5"`` → ``12.5``

## Backward compatibility

* ``extract_budget`` / ``extract_order`` / ``extract_invoice`` accept
  the original ``(document_id, text, document_confidence)`` signature
  and an optional ``pages`` keyword argument.
* ``persist_business_extraction`` accepts the original
  ``(db, document, text)`` signature and an optional ``pages``
  keyword argument.
* ``_apply_classification_and_extraction`` accepts an optional
  ``pages`` keyword argument.

Callers that do not pass ``pages`` get the legacy regex behaviour,
which is the same as before this change.
