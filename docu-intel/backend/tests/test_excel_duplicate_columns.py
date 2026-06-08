"""Test the Excel parser fix for duplicate column names.

The original bug: ``frame[col] = frame[col].str.strip()`` crashed with
``'DataFrame' object has no attribute 'str'`` when the header row had
duplicate names, because ``frame[duplicated_col]`` returns a DataFrame
(not a Series) and DataFrames have no ``.str`` accessor.

The fix: use positional indexing (``frame.iloc[:, i]``) which always
returns a Series regardless of duplicate column names.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.parsers.excel import _frame_to_markdown


def test_excel_duplicate_columns_does_not_crash():
    """The original crash: ``frame[col].str`` on a duplicate column
    returns a DataFrame which has no ``.str`` accessor."""
    df = pd.DataFrame({
        "Cliente": ["Hotel A", "Hotel B"],
        "Total": ["100", "200"],
        "Total": ["50", "75"],  # duplicate column name
    })
    # If the bug is present, this raises
    # ``AttributeError: 'DataFrame' object has no attribute 'str'``.
    md = _frame_to_markdown(df, "Test")
    assert "### Hoja: Test" in md


def test_excel_normal_columns_still_work():
    """The fix must not break the normal case with unique columns."""
    df = pd.DataFrame({
        "Cliente": ["Hotel A", "Hotel B", "Hotel C"],
        "Total": ["100", "200", "300"],
    })
    md = _frame_to_markdown(df, "Presupuestos")
    assert "### Hoja: Presupuestos" in md
    # With 3+ rows the table layout is used, otherwise it falls back
    # to a simple "label | value" list. Either way, the values must appear.
    assert "Hotel A" in md
    assert "Hotel B" in md
    assert "Hotel C" in md
    assert "100" in md
    assert "200" in md
    assert "300" in md


def test_excel_empty_sheet():
    """An empty sheet should produce a friendly placeholder, not crash."""
    df = pd.DataFrame()
    md = _frame_to_markdown(df, "Empty")
    assert "Empty" in md
    assert "vacía" in md.lower() or "vacia" in md.lower()
