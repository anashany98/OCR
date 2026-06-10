"""Tests for P5 — multi-sheet plan phase detection.

The phase detector is pure (no DB, no OCR) and extracts the
building phase and revision from the plan text. The tests pin
the contract so a future refactor cannot silently change the
detection rules.
"""
from __future__ import annotations

import pytest

from app.services.plan_extraction import extract_plan_phase


# ---------------------------------------------------------------------------
# Phase detection
# ---------------------------------------------------------------------------


def test_extract_plan_phase_detects_planta_baja():
    phase, revision = extract_plan_phase("PLANTA BAJA — Escala 1:50")
    assert phase == "PLANTA BAJA"


def test_extract_plan_phase_detects_planta_primera():
    phase, revision = extract_plan_phase("Planta primera del edificio")
    assert phase == "PLANTA PRIMERA"


def test_extract_plan_phase_detects_planta_segunda():
    phase, revision = extract_plan_phase("PLANTA SEGUNDA — Viviendas")
    assert phase == "PLANTA SEGUNDA"


def test_extract_plan_phase_detects_planta_number():
    phase, revision = extract_plan_phase("Planta 3 — Oficinas")
    assert phase is not None
    assert "3" in phase


def test_extract_plan_phase_detects_cubierta():
    phase, revision = extract_plan_phase("CUBIERTA — Instalaciones")
    assert phase == "CUBIERTA"


def test_extract_plan_phase_detects_sotano():
    phase, revision = extract_plan_phase("SÓTANO 1 — Aparcamientos")
    assert phase == "SÓTANO"


def test_extract_plan_phase_detects_alzado():
    phase, revision = extract_plan_phase("ALZADO NORTE — Fachada principal")
    assert phase is not None
    assert "NORTE" in phase


def test_extract_plan_phase_detects_seccion():
    phase, revision = extract_plan_phase("SECCIÓN A-A — Corte longitudinal")
    assert phase is not None
    assert "SECCI" in phase.upper()


def test_extract_plan_phase_returns_none_for_no_match():
    phase, revision = extract_plan_phase("Factura 245745 por importe de 12.450 EUR")
    assert phase is None
    assert revision is None


def test_extract_plan_phase_handles_empty_text():
    phase, revision = extract_plan_phase("")
    assert phase is None
    assert revision is None


# ---------------------------------------------------------------------------
# Revision detection
# ---------------------------------------------------------------------------


def test_extract_plan_phase_detects_revision_letter():
    phase, revision = extract_plan_phase("PLANTA BAJA REV: A")
    assert revision == "A"


def test_extract_plan_phase_detects_revision_number():
    phase, revision = extract_plan_phase("PLANTA PRIMERA REV01")
    assert revision == "01"


def test_extract_plan_phase_detects_revision_with_dash():
    phase, revision = extract_plan_phase("CUBIERTA Rev-02")
    assert revision == "02"


def test_extract_plan_phase_returns_none_revision_when_absent():
    phase, revision = extract_plan_phase("PLANTA BAJA")
    assert revision is None
