"""Markdown table -> entity extraction.

After a parser renders a spreadsheet or PDF page as a markdown table, this
module extracts structured entities (line items for a presupuesto, pedido,
or factura) from that markdown. The goal is to make the LLM's job easier
by handing it pre-extracted facts it would otherwise have to re-discover
from raw text.

The extractor is rule-based, not LLM-based: it's cheap, deterministic,
and good enough for the high-confidence columns we care about
(article / description / quantity / unit price / total).
"""

from __future__ import annotations

import re
from typing import Any

# Column keywords we look for in the header row. Spanish + English.
_COL_NUMBER = re.compile(r"^(art|articulo|ref|referencia|sku|codigo|código|code)$", re.IGNORECASE)
_COL_DESC = re.compile(
    r"^(desc|descripcion|descripción|concepto|producto|denominacion|denominación|name|detalle)$",
    re.IGNORECASE,
)
_COL_QTY = re.compile(r"^(cant|cantidad|qty|quantity|uds|unidades)$", re.IGNORECASE)
_COL_UNIT = re.compile(r"^(unidad|unit|u\.?\s?d\.?)$", re.IGNORECASE)
_COL_UNIT_PRICE = re.compile(
    r"^(precio\s*uni|precio\s*unidad|unit\s*price|pvp\s*uni|importe\s*uni)$", re.IGNORECASE
)
_COL_TOTAL = re.compile(
    r"^(total|subtotal|importe|pvp|amount|precio|precio\s*total)$", re.IGNORECASE
)
_COL_DISCOUNT = re.compile(r"^(dto|descuento|discount)$", re.IGNORECASE)
_COL_TAX = re.compile(r"^(iva|tax)$", re.IGNORECASE)

# Recognise prices like 1.234,56 / 1,234.56 / 25,91 / 25.91 / 1234
_PRICE_RE = re.compile(r"^\s*-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?\s*$")
_QTY_RE = re.compile(r"^\s*-?\d+(?:[.,]\d+)?\s*$")


def _parse_money(value: str) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in {"-", "—", "n/a", "N/A"}:
        return None
    if not _PRICE_RE.match(s):
        return None
    # Normalise: figure out whether comma is thousands or decimal.
    has_dot = "." in s
    has_comma = "," in s
    if has_comma and has_dot:
        # The rightmost separator is the decimal one.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_comma and not has_dot:
        # Single comma: treat as decimal (Spanish/Italian style).
        s = s.replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _parse_qty(value: str) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in {"-", "—"}:
        return None
    if not _QTY_RE.match(s):
        return None
    has_dot = "." in s
    has_comma = "," in s
    if has_comma and not has_dot:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _classify_column(header: str) -> str:
    h = header.strip().lower()
    if _COL_NUMBER.match(h):
        return "reference"
    if _COL_DESC.match(h):
        return "description"
    if _COL_QTY.match(h):
        return "quantity"
    if _COL_UNIT.match(h):
        return "unit"
    if _COL_UNIT_PRICE.match(h):
        return "unit_price"
    if _COL_TOTAL.match(h):
        return "total_price"
    if _COL_DISCOUNT.match(h):
        return "discount"
    if _COL_TAX.match(h):
        return "tax"
    return ""


def parse_markdown_table(md: str) -> list[dict[str, Any]]:
    """Parse a markdown table into a list of dicts (one per row). The
    first row is treated as the header. Returns an empty list when the
    input does not look like a markdown table."""
    if not md:
        return []
    lines = [ln.rstrip() for ln in md.splitlines() if ln.strip()]
    if len(lines) < 2:
        return []
    # A markdown table has the pipe-separated header and a separator
    # row that looks like | --- | --- |. We find the first separator.
    sep_idx = None
    for i, ln in enumerate(lines[1:], start=1):
        if re.fullmatch(r"\|\s*(:?-{2,}:?\s*\|\s*)+:?-{2,}:?\s*\|?", ln.strip()):
            sep_idx = i
            break
    if sep_idx is None:
        return []
    header = [c.strip() for c in lines[sep_idx - 1].strip().strip("|").split("|")]
    rows: list[dict[str, Any]] = []
    for ln in lines[sep_idx + 1 :]:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < len(header):
            cells = cells + [""] * (len(header) - len(cells))
        elif len(cells) > len(header):
            cells = cells[: len(header) - 1] + [" | ".join(cells[len(header) - 1 :])]
        row = {h: cells[i] for i, h in enumerate(header) if h}
        if any(v.strip() for v in row.values()):
            rows.append(row)
    return rows


def extract_line_items(md: str) -> list[dict[str, Any]]:
    """Parse a markdown table and return it as a list of normalised
    line items, picking up description / quantity / unit price / total
    columns by name. Only rows that have a description are returned."""
    rows = parse_markdown_table(md)
    if not rows:
        return []
    # Map header -> classified role.
    classified: list[tuple[str, str, int]] = []
    for idx, header in enumerate(rows[0].keys()):
        role = _classify_column(header)
        if role:
            classified.append((header, role, idx))
    if not classified:
        return []
    # Convert every row using the same header set.
    items: list[dict[str, Any]] = []
    for r in rows:
        # rows is a list of dicts {header: cell} since parse_markdown_table
        # returns list of dicts. Re-align using original row order.
        cells = list(r.values())
        line: dict[str, Any] = {}
        for header, role, idx in classified:
            if idx >= len(cells):
                continue
            raw = cells[idx]
            if role in {"unit_price", "total_price", "discount", "tax"}:
                val = _parse_money(raw)
                if val is not None:
                    line[role] = val
            elif role == "quantity":
                val = _parse_qty(raw)
                if val is not None:
                    line[role] = val
            else:
                val = (raw or "").strip()
                if val:
                    line[role] = val
        # Only keep rows that look like a line item.
        if line.get("description") or line.get("reference"):
            items.append(line)
    return items


def extract_all_line_items(text: str) -> list[dict[str, Any]]:
    """Run extract_line_items against every markdown table embedded in
    the text. Returns a flat list of line items in document order."""
    if not text or "|" not in text:
        return []
    out: list[dict[str, Any]] = []
    chunks = text.split("--- Tablas detectadas ---")
    for chunk in chunks:
        out.extend(extract_line_items(chunk))
    return out


def find_total_amount(text: str) -> tuple[float | None, str | None]:
    """Look for a "TOTAL" row in any embedded markdown table. Returns
    (value, label) where label is the row's reference/description so the
    caller can quote it back. Prefers "PVP/TOTAL" then "TOTAL" then
    "Importe" then the largest row in the "total" column."""
    items = extract_all_line_items(text)
    if not items:
        return None, None
    # 1) explicit TOTAL row
    for it in items:
        ref = (it.get("reference") or "").upper()
        if "TOTAL" in ref and it.get("total_price") is not None:
            label = it.get("description") or it.get("reference") or "TOTAL"
            return it["total_price"], label
        desc = (it.get("description") or "").upper()
        if "TOTAL" in desc and it.get("total_price") is not None:
            return it["total_price"], it["description"]
    # 2) Largest total_price wins.
    best: tuple[float | None, str | None] = (None, None)
    for it in items:
        val = it.get("total_price")
        if val is None:
            continue
        if best[0] is None or val > best[0]:
            best = (val, it.get("description") or it.get("reference"))
    return best
