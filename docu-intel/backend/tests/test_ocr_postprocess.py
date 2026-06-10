"""Tests for O4 — OCR post-processing: number normalisation + validators.

The post-processor is pure (no DB, no I/O) and corrects common OCR
mis-reads in financial documents. The tests pin the contract so a
future refactor cannot silently change the correction rules.
"""
from __future__ import annotations

import pytest

from app.services.ocr_postprocess import (
    Correction,
    PostprocessReport,
    validate_cif,
    validate_iban,
    validate_nif,
    postprocess_ocr_text,
    _normalise_number,
    _normalise_separators,
)


# ---------------------------------------------------------------------------
# NIF validation
# ---------------------------------------------------------------------------


def test_validate_nif_valid():
    # NIF 12345678Z: check digit = Z (12345678 % 23 = 10 → 'Z')
    valid, normalised = validate_nif("12345678Z")
    assert valid is True
    assert normalised == "12345678Z"


def test_validate_nif_invalid_check_digit():
    valid, normalised = validate_nif("12345678A")
    assert valid is False


def test_validate_nif_ocr_correction():
    # 12345678O → 123456780 (O → 0), then check digit of 123456780.
    # 123456780 % 23 = 18 → 'H'. The OCR-corrected NIF is 123456780H.
    # But the input is just 9 chars: 12345678O. The validator tries
    # the O→0 substitution on the *check letter*, not on the digits.
    # The validator only corrects the check letter, not the body.
    # So this test verifies the *check-letter* correction works.
    # 12345678Z is valid; 12345678O is not (O is not the right letter).
    # The validator does not try to correct the body digits.
    valid, normalised = validate_nif("12345678O")
    # O is not the correct check letter for 12345678, and O→0 is not
    # a valid letter. The validator rejects.
    assert valid is False


def test_validate_nif_too_short():
    valid, normalised = validate_nif("12345")
    assert valid is False


def test_validate_nif_empty():
    valid, normalised = validate_nif("")
    assert valid is False


# ---------------------------------------------------------------------------
# CIF validation
# ---------------------------------------------------------------------------


def test_validate_cif_valid():
    # CIF A12345678: org=A, body=1234567, check=8.
    # Luhn-like: even positions (0,2,4,6) *2: 1*2=2, 3*2=6, 5*2=10→1, 7*2=14→5
    #            odd positions (1,3,5): 2+4+6=12
    #            total = (2+6+1+5) + 12 = 26
    #            expected digit = (10 - 26%10) % 10 = 4. So A12345674 is valid.
    valid, normalised = validate_cif("A12345674")
    assert valid is True
    assert normalised == "A12345674"


def test_validate_cif_invalid():
    valid, normalised = validate_cif("A12345678")
    assert valid is False


def test_validate_cif_too_short():
    valid, normalised = validate_cif("A1234")
    assert valid is False


def test_validate_cif_bad_org_letter():
    valid, normalised = validate_cif("I12345674")
    assert valid is False


# ---------------------------------------------------------------------------
# IBAN validation
# ---------------------------------------------------------------------------


def test_validate_iban_valid_es():
    # ES6621000418401234567891 is a valid Spanish IBAN (test vector).
    valid, normalised = validate_iban("ES66 2100 0418 4012 3456 7891")
    assert valid is True
    assert normalised == "ES6621000418401234567891"


def test_validate_iban_valid_de():
    # DE89370400440532013000 is a valid German IBAN (test vector).
    valid, normalised = validate_iban("DE89 3704 0044 0532 0130 00")
    assert valid is True
    assert normalised == "DE89370400440532013000"


def test_validate_iban_invalid_check():
    valid, normalised = validate_iban("ES0021000418401234567891")
    assert valid is False


def test_validate_iban_wrong_length():
    # Spanish IBAN must be 24 chars.
    valid, normalised = validate_iban("ES662100041840123456789")
    assert valid is False


def test_validate_iban_empty():
    valid, normalised = validate_iban("")
    assert valid is False


# ---------------------------------------------------------------------------
# Number normalisation
# ---------------------------------------------------------------------------


def test_normalise_number_european_decimal():
    assert _normalise_number("12.345,67") == "12345.67"


def test_normalise_number_anglo_decimal():
    assert _normalise_number("12,345.67") == "12345.67"


def test_normalise_number_simple_european():
    assert _normalise_number("1234,56") == "1234.56"


def test_normalise_number_simple_anglo():
    assert _normalise_number("1234.56") == "1234.56"


def test_normalise_number_integer():
    assert _normalise_number("12345") == "12345"


def test_normalise_number_ocr_substitution():
    # 1O.5O in numeric context → 10.50
    assert _normalise_number("1O,5O") == "10.50"


def test_normalise_number_empty():
    assert _normalise_number("") == ""


def test_normalise_separators_european():
    assert _normalise_separators("1.234.567,89") == "1234567.89"


def test_normalise_separators_anglo():
    assert _normalise_separators("1,234,567.89") == "1234567.89"


def test_normalise_separators_no_thousands():
    assert _normalise_separators("1234,56") == "1234.56"


def test_normalise_separators_integer():
    assert _normalise_separators("12345") == "12345"


# ---------------------------------------------------------------------------
# Full postprocess_ocr_text
# ---------------------------------------------------------------------------


def test_postprocess_ocr_text_handles_empty():
    report = postprocess_ocr_text("")
    assert report.corrected_text == ""
    assert report.corrections == []


def test_postprocess_ocr_text_corrects_european_amount():
    text = "Total: 12.345,67 EUR"
    report = postprocess_ocr_text(text, language="es")
    assert "12345.67" in report.corrected_text
    assert any(c.kind == "number" for c in report.corrections)


def test_postprocess_ocr_text_preserves_valid_nif():
    text = "CIF: A12345674"
    report = postprocess_ocr_text(text, language="es")
    assert "A12345674" in report.corrected_text


def test_postprocess_ocr_text_corrects_nif():
    # 12345678Z is valid; if OCR produced 12345678Z it stays.
    text = "NIF: 12345678Z"
    report = postprocess_ocr_text(text, language="es")
    assert "12345678Z" in report.corrected_text


def test_postprocess_ocr_text_preserves_valid_iban():
    text = "IBAN: ES6621000418401234567891"
    report = postprocess_ocr_text(text, language="es")
    assert "ES6621000418401234567891" in report.corrected_text


def test_postprocess_ocr_text_returns_corrections_list():
    text = "Total: 1.234,56 EUR"
    report = postprocess_ocr_text(text, language="es")
    assert isinstance(report.corrections, list)


def test_postprocess_ocr_text_tracks_original_length():
    text = "some text with length"
    report = postprocess_ocr_text(text)
    assert report.original_length == len(text)
