"""Tests for the S0.1 golden OCR scorer.

These tests are deliberately deterministic: they build GoldenFixture
objects in memory and feed them hand-crafted OCR results. This keeps
the test fast, free of PyMuPDF/Tesseract dependencies, and easy to
reason about. The scorer is the contract that the real OCR engine
must respect; the test pins the contract down so future refactors
cannot silently change what we measure.

The tests in ``test_repo_golden_fixtures_are_loadable`` (and the
tests that exercise the manifest+page files) do touch the on-disk
fixtures that ship in the repo, which is the integration-level check
we want: if the manifest format breaks, these tests fail loudly.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.golden_ocr import (
    DEFAULT_GATES,
    GoldenFixture,
    GoldenSample,
    PageGroundTruth,
    PageScore,
    character_error_rate,
    keyword_recall,
    load_all_fixtures,
    load_fixture,
    load_manifest,
    score_fixture,
    sha256_of_file,
    word_recall,
)


# ---------------------------------------------------------------------------
# Unit tests for the scoring functions
# ---------------------------------------------------------------------------


def test_character_error_rate_perfect_match_is_zero():
    text = "Factura 245745 total 1234,56 EUR"
    assert character_error_rate(text, text) == 0.0


def test_character_error_rate_empty_inputs():
    assert character_error_rate("", "") == 0.0
    assert character_error_rate("hello", "") == 1.0
    assert character_error_rate("", "hello") == 1.0


def test_character_error_rate_partial_match_is_between_zero_and_one():
    ref = "Factura 245745 total 1234,56 EUR"
    hyp = "Factura 245745 total 1234.56 EUR"  # one char different
    cer = character_error_rate(ref, hyp)
    assert 0.0 < cer < 0.05  # very small CER for one character


def test_character_error_rate_normalises_whitespace():
    # A line break in the hypothesis should not count as an error.
    ref = "Factura total EUR"
    hyp = "Factura\n  total\nEUR"
    assert character_error_rate(ref, hyp) == 0.0


def test_word_recall_perfect_match_is_one():
    text = "Factura 245745 total 1234,56 EUR"
    assert word_recall(text, text) == 1.0


def test_word_recall_empty_reference_is_one():
    assert word_recall("", "anything") == 1.0


def test_word_recall_empty_hypothesis_is_zero():
    assert word_recall("Factura total", "") == 0.0


def test_word_recall_partial():
    # 2 of 3 unique words present.
    assert word_recall("Factura 245745 total", "factura 245745 importe") == pytest.approx(2 / 3)


def test_keyword_recall_empty_keywords_is_one():
    assert keyword_recall([], "anything") == 1.0


def test_keyword_recall_empty_hypothesis_is_zero():
    assert keyword_recall(["EUR", "NIF"], "") == 0.0


def test_keyword_recall_case_insensitive_substring():
    assert keyword_recall(["eur", "garcia"], "Factura 12,50 EUR cliente Garcia") == 1.0
    assert keyword_recall(["eur", "missing"], "Factura 12,50 EUR") == 0.5


# ---------------------------------------------------------------------------
# score_fixture — end-to-end
# ---------------------------------------------------------------------------


def _sample(
    *,
    doc_type: str = "presupuesto",
    page_count: int = 1,
    keywords: list[str] | None = None,
) -> GoldenSample:
    return GoldenSample(
        id="t1",
        source_filename="t1.pdf",
        document_type=doc_type,
        page_count=page_count,
        sha256="0" * 64,
        keywords=keywords or [],
    )


def test_score_fixture_perfect_match_passes():
    fixture = GoldenFixture(
        sample=_sample(),
        pages=[PageGroundTruth(page_number=1, text="Factura 245745 total 1234,56 EUR")],
    )
    score = score_fixture(
        fixture,
        ocr_pages={1: "Factura 245745 total 1234,56 EUR"},
    )
    assert score.passed
    assert score.mean_text_cer == 0.0
    assert score.mean_text_recall == 1.0


def test_score_fixture_detects_corrupted_text():
    fixture = GoldenFixture(
        sample=_sample(),
        pages=[PageGroundTruth(page_number=1, text="Factura 245745 total 1234,56 EUR")],
    )
    # The OCR output mangles the number; the rest is correct.
    score = score_fixture(
        fixture,
        ocr_pages={1: "Factura XXXXXX total 1234,56 EUR"},
    )
    # Word recall drops because '245745' is gone.
    assert score.mean_text_recall < 1.0
    assert not score.passed


def test_score_fixture_flags_missing_keyword():
    fixture = GoldenFixture(
        sample=_sample(keywords=["B12345678", "12,50"]),
        pages=[PageGroundTruth(page_number=1, text="Factura total 12,50 EUR cliente B12345678")],
    )
    # OCR misses the NIF.
    score = score_fixture(fixture, ocr_pages={1: "Factura total 12,50 EUR cliente"})
    assert not score.passed
    assert "B12345678" in score.detail


def test_score_fixture_handles_missing_pages():
    fixture = GoldenFixture(
        sample=_sample(page_count=2),
        pages=[
            PageGroundTruth(page_number=1, text="hello"),
            PageGroundTruth(page_number=2, text="world"),
        ],
    )
    # OCR returned only page 1.
    score = score_fixture(fixture, ocr_pages={1: "hello"})
    assert not score.passed
    # The missing page should have CER 1.0 and recall 0.0.
    page2 = score.pages[1]
    assert page2.text_cer == 1.0
    assert page2.text_recall == 0.0


def test_score_fixture_respects_custom_gates():
    fixture = GoldenFixture(
        sample=_sample(),
        pages=[PageGroundTruth(page_number=1, text="hello world")],
    )
    # Strict gates: a single-char error should fail.
    strict = score_fixture(
        fixture,
        ocr_pages={1: "hello World"},  # one char diff
        max_text_cer=0.0,
    )
    assert not strict.passed
    # Loose gates: same output should pass.
    loose = score_fixture(
        fixture,
        ocr_pages={1: "hello World"},
        max_text_cer=0.50,
        min_text_recall=0.50,
    )
    assert loose.passed


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------


def test_load_manifest_parses_samples_list(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({
            "samples": [
                {
                    "id": "x",
                    "source_filename": "x.pdf",
                    "document_type": "pedido",
                    "page_count": 3,
                    "sha256": "abc",
                    "keywords": ["EUR"],
                }
            ]
        }),
        encoding="utf-8",
    )
    samples = load_manifest(manifest)
    assert len(samples) == 1
    assert samples[0].id == "x"
    assert samples[0].page_count == 3
    assert samples[0].keywords == ["EUR"]


def test_load_fixture_reads_page_files(tmp_path: Path):
    fixture_dir = tmp_path / "fix"
    fixture_dir.mkdir()
    (fixture_dir / "manifest.json").write_text(
        json.dumps({
            "samples": [
                {
                    "id": "f",
                    "source_filename": "f.pdf",
                    "document_type": "albaran",
                    "page_count": 2,
                    "sha256": "x",
                    "keywords": [],
                }
            ]
        }),
        encoding="utf-8",
    )
    (fixture_dir / "page_1.txt").write_text("page one text", encoding="utf-8")
    (fixture_dir / "page_2.txt").write_text("page two text", encoding="utf-8")
    fixture = load_fixture(fixture_dir)
    assert fixture.sample.id == "f"
    assert len(fixture.pages) == 2
    assert fixture.ground_truth_for(1) == "page one text"


def test_load_fixture_raises_when_page_file_missing(tmp_path: Path):
    fixture_dir = tmp_path / "fix"
    fixture_dir.mkdir()
    (fixture_dir / "manifest.json").write_text(
        json.dumps({
            "samples": [
                {
                    "id": "f",
                    "source_filename": "f.pdf",
                    "document_type": "albaran",
                    "page_count": 2,
                    "sha256": "x",
                    "keywords": [],
                }
            ]
        }),
        encoding="utf-8",
    )
    (fixture_dir / "page_1.txt").write_text("page one", encoding="utf-8")
    # page_2.txt missing
    with pytest.raises(FileNotFoundError):
        load_fixture(fixture_dir)


def test_load_all_fixtures_skips_dirs_without_manifest(tmp_path: Path):
    (tmp_path / "with_manifest").mkdir()
    (tmp_path / "with_manifest" / "manifest.json").write_text(
        json.dumps({
            "samples": [
                {
                    "id": "a",
                    "source_filename": "a.pdf",
                    "document_type": "otro",
                    "page_count": 1,
                    "sha256": "x",
                    "keywords": [],
                }
            ]
        }),
        encoding="utf-8",
    )
    (tmp_path / "with_manifest" / "page_1.txt").write_text("x", encoding="utf-8")
    (tmp_path / "no_manifest").mkdir()  # ignored

    fixtures = load_all_fixtures(tmp_path)
    assert len(fixtures) == 1
    assert fixtures[0].sample.id == "a"


# ---------------------------------------------------------------------------
# SHA256 helper
# ---------------------------------------------------------------------------


def test_sha256_of_file_matches_hashlib(tmp_path: Path):
    p = tmp_path / "data.bin"
    p.write_bytes(b"some bytes")
    import hashlib

    expected = hashlib.sha256(b"some bytes").hexdigest()
    assert sha256_of_file(p) == expected


# ---------------------------------------------------------------------------
# Integration: the on-disk fixtures shipped in the repo must be loadable.
# ---------------------------------------------------------------------------


GOLDEN_ROOT = Path(__file__).resolve().parent / "fixtures" / "golden_ocr"


@pytest.mark.skipif(not GOLDEN_ROOT.exists(), reason="golden_ocr fixtures not present")
def test_repo_golden_fixtures_are_loadable():
    """The fixtures shipped under tests/fixtures/golden_ocr/ must all
    parse without errors. This is the integration-level sanity check
    that protects against manifest-format drift."""
    fixtures = load_all_fixtures(GOLDEN_ROOT)
    assert fixtures, "no fixtures found in the repo"
    for fix in fixtures:
        assert fix.sample.id
        assert fix.sample.source_filename
        assert fix.sample.page_count == len(fix.pages)
        assert fix.sample.sha256
        # Every page file must have been read and be a non-None string.
        for page in fix.pages:
            assert isinstance(page.text, str)


@pytest.mark.skipif(not GOLDEN_ROOT.exists(), reason="golden_ocr fixtures not present")
def test_repo_golden_fixtures_have_sane_manifests():
    """Loose sanity checks on every shipped manifest: ids are
    non-empty, sha256 is 64 hex chars, page_count is >= 1."""
    import re as _re
    fixtures = load_all_fixtures(GOLDEN_ROOT)
    hex_re = _re.compile(r"^[0-9a-f]{64}$")
    for fix in fixtures:
        assert hex_re.match(fix.sample.sha256), f"bad sha256 in {fix.sample.id}"
        assert fix.sample.page_count >= 1, f"page_count<1 in {fix.sample.id}"
        assert fix.sample.document_type in {
            "presupuesto", "pedido", "factura", "albaran", "plano", "otro",
        }, f"unknown document_type in {fix.sample.id}"


def test_default_gates_have_sensible_values():
    """The default gates are the contract the CI uses. Pin them so an
    accidental 'weakening' (e.g. max_text_cer=0.99) shows up in
    code review instead of slipping through."""
    assert DEFAULT_GATES["max_text_cer"] <= 0.20
    assert DEFAULT_GATES["min_text_recall"] >= 0.70
    assert DEFAULT_GATES["min_keyword_recall"] >= 0.90


def test_score_fixture_flags_empty_ground_truth():
    """A fixture with no per-page text and no keywords cannot be
    scored. Returning a passing score would let unreviewed fixtures
    silently pass CI; the scorer must fail them with a clear hint
    so the team knows to bootstrap ground truth via Tesseract."""
    fixture = GoldenFixture(
        sample=_sample(),
        pages=[PageGroundTruth(page_number=1, text="")],
    )
    score = score_fixture(
        fixture,
        ocr_pages={1: "anything the OCR produced"},
    )
    assert not score.passed
    assert "empty ground truth" in score.detail
    assert "Tesseract" in score.detail or "update_golden_ocr" in score.detail


def test_score_fixture_empty_pages_but_with_keywords_uses_keyword_recall():
    """A fixture whose pages are all empty (scan-only PDFs whose
    bootstrap never ran Tesseract) but which has keywords can still
    be partially scored via the keyword recall. If none of the
    keywords are present, the fixture still fails — but for the
    *right* reason (missing keywords), not for a bogus 'empty GT'
    sentinel."""
    fixture = GoldenFixture(
        sample=_sample(keywords=["EUR", "12,50"]),
        pages=[PageGroundTruth(page_number=1, text="")],
    )
    score = score_fixture(
        fixture,
        ocr_pages={1: "factura 12,50 EUR cliente acme"},
    )
    assert score.passed
    assert score.overall_keyword_recall == 1.0
