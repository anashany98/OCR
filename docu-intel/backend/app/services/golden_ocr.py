"""S0.1 — Golden OCR fixture scoring.

The point of this module is to give us a deterministic, dependency-free
way to measure whether a change to the OCR pipeline (Tesseract bump,
PaddleOCR upgrade, cascade rebalancing, pre-processing tweak) made
extraction quality better or worse.

The fixtures live in ``tests/fixtures/golden_ocr/`` and contain:

* a ``manifest.json`` that lists every sample (filename, document
  type, page count, sha256);
* one ``page_N.txt`` per page with the *ground-truth* text the OCR is
  expected to produce;
* a ``keywords.json`` per sample with substrings the OCR is expected
  to surface (importes, NIFs, room names, scales) — these are the
  cheap signal we use for fast CI checks.

The scorer computes three signals:

* **page_text_cer** — character error rate of the extracted page text
  against the ground truth (via ``difflib.SequenceMatcher``).
* **page_text_recall** — fraction of ground-truth *words* that appear
  in the OCR output (case-insensitive, substring-friendly).
* **keyword_recall** — fraction of the expected keywords the OCR
  output contains.

None of these require the real OCR engine, the database, or the FastAPI
app. The test harness passes in pre-computed OCR results as
``OcrResult`` objects, which keeps the tests fast and lets the same
scoring code be reused both in CI (with golden results baked into the
repo) and locally (with the live engine).
"""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger("app.services.golden_ocr")


# ---------------------------------------------------------------------------
# Manifest + ground-truth schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoldenSample:
    """One entry in the golden manifest.

    Fields:
        id: stable identifier (filename stem, lowercased + spaces → underscores).
        source_filename: the original PDF basename.
        document_type: presupuesto | pedido | factura | albaran | plano | otro.
        page_count: number of pages in the source PDF.
        sha256: sha256 of the source PDF bytes (guards against silent
            fixture drift: if the PDF changes, sha256 changes and the
            CI gate demands a manual ``--update``).
        keywords: list of substrings the OCR output is expected to
            contain somewhere across all pages. Empty = no keyword gate.
    """

    id: str
    source_filename: str
    document_type: str
    page_count: int
    sha256: str
    keywords: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GoldenSample":
        return cls(
            id=str(data["id"]),
            source_filename=str(data["source_filename"]),
            document_type=str(data.get("document_type", "otro")),
            page_count=int(data.get("page_count", 1)),
            sha256=str(data.get("sha256", "")),
            keywords=[str(x) for x in data.get("keywords", []) or []],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PageGroundTruth:
    """Ground truth for a single page.

    ``text`` is the canonical, line-broken text the OCR is expected to
    produce. Whitespace is normalised before comparison so the scorer
    is not sensitive to incidental line breaks.
    """

    page_number: int
    text: str


@dataclass(frozen=True)
class GoldenFixture:
    """A complete fixture: one sample + one PageGroundTruth per page."""

    sample: GoldenSample
    pages: list[PageGroundTruth]

    def ground_truth_for(self, page_number: int) -> str | None:
        for page in self.pages:
            if page.page_number == page_number:
                return page.text
        return None


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_manifest(manifest_path: str | Path) -> list[GoldenSample]:
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    samples_raw = data.get("samples", [])
    return [GoldenSample.from_dict(entry) for entry in samples_raw]


def load_fixture(fixture_dir: str | Path) -> GoldenFixture:
    """Load a single fixture from its directory.

    Expected layout::

        fixture_dir/
        ├── manifest.json           (required)
        ├── page_1.txt              (required if page_count >= 1)
        ├── page_2.txt              (required if page_count >= 2)
        └── ...
    """
    fixture_dir = Path(fixture_dir)
    manifest_path = fixture_dir / "manifest.json"
    samples = load_manifest(manifest_path)
    if not samples:
        raise ValueError(f"manifest at {manifest_path} has no samples")
    sample = samples[0]  # one sample per directory by convention

    pages: list[PageGroundTruth] = []
    for n in range(1, sample.page_count + 1):
        text_path = fixture_dir / f"page_{n}.txt"
        if not text_path.exists():
            raise FileNotFoundError(f"Missing ground truth: {text_path}")
        text = text_path.read_text(encoding="utf-8")
        pages.append(PageGroundTruth(page_number=n, text=text))
    return GoldenFixture(sample=sample, pages=pages)


def load_all_fixtures(root_dir: str | Path) -> list[GoldenFixture]:
    """Load every fixture in the golden directory.

    A "fixture" is any subdirectory of ``root_dir`` that contains a
    ``manifest.json``. Subdirectories without one are ignored.
    """
    root = Path(root_dir)
    fixtures: list[GoldenFixture] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "manifest.json").exists():
            continue
        fixtures.append(load_fixture(child))
    return fixtures


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _normalise(text: str) -> str:
    """Collapse whitespace and strip. Keeps unicode letters/digits/punct."""
    if not text:
        return ""
    # Collapse all whitespace runs into single spaces; trim.
    return re.sub(r"\s+", " ", text).strip()


def _tokenise(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r"\w+", text.lower())


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Character error rate using ``difflib.SequenceMatcher``.

    Returns a float in ``[0, 1]`` where ``0`` = perfect match and
    ``1`` = everything wrong. We compute ``1 - ratio`` clamped to
    ``[0, 1]``. The SequenceMatcher ratio is on the *characters* of
    the longer string, which is a good enough proxy for short pages
    and avoids depending on edit-distance libraries.
    """
    ref = _normalise(reference)
    hyp = _normalise(hypothesis)
    if not ref and not hyp:
        return 0.0
    if not ref or not hyp:
        return 1.0
    matcher = difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False)
    return max(0.0, min(1.0, 1.0 - matcher.ratio()))


def word_recall(reference: str, hypothesis: str) -> float:
    """Fraction of ground-truth words that appear in the hypothesis.

    Words are normalised (lower-cased, stripped of punctuation) and a
    ground-truth word counts as recalled when it appears as a
    *substring* of the hypothesis token stream. This makes the metric
    robust to small tokenisation differences between OCR engines.
    """
    ref_tokens = _tokenise(reference)
    if not ref_tokens:
        return 1.0
    hyp_text = _normalise(hypothesis).lower()
    if not hyp_text:
        return 0.0
    hits = sum(1 for tok in ref_tokens if tok in hyp_text)
    return hits / len(ref_tokens)


def keyword_recall(keywords: Iterable[str], hypothesis: str) -> float:
    """Fraction of expected keywords present in the hypothesis.

    Case-insensitive substring match. Returns 1.0 when there are no
    keywords (so a fixture without a keyword list is not penalised).
    """
    keywords = list(keywords)
    if not keywords:
        return 1.0
    haystack = _normalise(hypothesis).lower()
    if not haystack:
        return 0.0
    hits = sum(1 for kw in keywords if kw.lower() in haystack)
    return hits / len(keywords)


# ---------------------------------------------------------------------------
# Per-page and aggregate results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PageScore:
    page_number: int
    text_cer: float
    text_recall: float
    keyword_recall: float
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class FixtureScore:
    sample: GoldenSample
    pages: list[PageScore]
    mean_text_cer: float
    mean_text_recall: float
    mean_keyword_recall: float
    overall_keyword_recall: float
    passed: bool
    detail: str = ""


# Default gates. CI may want to tune these — the gate values are
# parameters on ``score_fixture`` so tests can pass tighter or looser
# thresholds per fixture.
DEFAULT_GATES = {
    "max_text_cer": 0.10,             # <= 10 % character error rate
    "min_text_recall": 0.80,          # >= 80 % of GT words present
    "min_keyword_recall": 1.0,        # every expected keyword must appear
}


def score_fixture(
    fixture: GoldenFixture,
    ocr_pages: dict[int, str],
    *,
    max_text_cer: float = DEFAULT_GATES["max_text_cer"],
    min_text_recall: float = DEFAULT_GATES["min_text_recall"],
    min_keyword_recall: float = DEFAULT_GATES["min_keyword_recall"],
) -> FixtureScore:
    """Score a fixture against OCR output.

    Args:
        fixture: the golden fixture with ground truth.
        ocr_pages: mapping ``page_number -> extracted text``. Missing
            pages count as failures.
        max_text_cer: per-page CER ceiling.
        min_text_recall: per-page word-recall floor.
        min_keyword_recall: per-fixture keyword recall floor.

    A fixture with an **empty ground truth** (no per-page text and no
    keywords) cannot be scored: there is nothing to compare against,
    so any OCR output would trivially match. We return a failing
    score with an explicit ``empty_ground_truth`` detail so the CI
    gate cannot be silently green-stamped by an unreviewed fixture.
    """
    has_any_gt = any(p.text.strip() for p in fixture.pages) or bool(fixture.sample.keywords)
    if not has_any_gt:
        empty_page = PageScore(
            page_number=1,
            text_cer=1.0,
            text_recall=0.0,
            keyword_recall=0.0,
            passed=False,
            detail="empty ground truth",
        )
        return FixtureScore(
            sample=fixture.sample,
            pages=[empty_page],
            mean_text_cer=1.0,
            mean_text_recall=0.0,
            mean_keyword_recall=0.0,
            overall_keyword_recall=0.0,
            passed=False,
            detail="empty ground truth: run scripts/update_golden_ocr --force in an environment with Tesseract (e.g. Docker)",
        )

    page_scores: list[PageScore] = []
    overall_hyp = ""
    pages_with_gt = [p for p in fixture.pages if p.text.strip()]
    for page_gt in fixture.pages:
        hyp = ocr_pages.get(page_gt.page_number, "")
        overall_hyp += "\n" + hyp
        if not page_gt.text.strip():
            # No per-page ground truth (scan-only fixture whose
            # Tesseract pass never ran). Skip the per-page gate for
            # this page; the keyword gate (computed at the fixture
            # level) still applies.
            page_scores.append(
                PageScore(
                    page_number=page_gt.page_number,
                    text_cer=0.0,
                    text_recall=1.0,
                    keyword_recall=1.0,
                    passed=True,
                    detail="no per-page ground truth; fixture scored on keywords only",
                )
            )
            continue
        cer = character_error_rate(page_gt.text, hyp)
        wr = word_recall(page_gt.text, hyp)
        passed = cer <= max_text_cer and wr >= min_text_recall
        detail = "" if passed else (
            f"CER={cer:.3f} (gate {max_text_cer:.3f}); "
            f"recall={wr:.3f} (gate {min_text_recall:.3f})"
        )
        page_scores.append(
            PageScore(
                page_number=page_gt.page_number,
                text_cer=cer,
                text_recall=wr,
                keyword_recall=1.0,  # per-page, unused here
                passed=passed,
                detail=detail,
            )
        )

    # Keyword recall is computed at the *fixture* level (across all
    # pages) because a keyword like "B12345678" can legitimately land
    # on any page of a multi-page PDF.
    kr = keyword_recall(fixture.sample.keywords, overall_hyp)
    # Only the pages that *had* a ground truth participate in the
    # page-level gate; pages that were skipped because they have no
    # GT are excluded.
    pages_with_gt_passed = all(
        p.passed for p, gt in zip(page_scores, fixture.pages) if gt.text.strip()
    )
    passed = pages_with_gt_passed and kr >= min_keyword_recall
    detail = ""
    if not passed:
        reasons = []
        if not pages_with_gt_passed:
            failed_pages = [
                p.page_number
                for p, gt in zip(page_scores, fixture.pages)
                if gt.text.strip() and not p.passed
            ]
            reasons.append(f"pages {failed_pages} failed CER/recall gate")
        if kr < min_keyword_recall:
            reasons.append(
                f"keyword recall {kr:.3f} < gate {min_keyword_recall:.3f} "
                f"(missing: {[k for k in fixture.sample.keywords if k.lower() not in overall_hyp.lower()]})"
            )
        detail = "; ".join(reasons)

    if pages_with_gt:
        mean_cer = sum(p.text_cer for p, gt in zip(page_scores, fixture.pages) if gt.text.strip()) / len(pages_with_gt)
        mean_recall = sum(p.text_recall for p, gt in zip(page_scores, fixture.pages) if gt.text.strip()) / len(pages_with_gt)
    else:
        # No per-page GT at all; we are scoring on keywords only.
        mean_cer = 0.0
        mean_recall = 1.0

    return FixtureScore(
        sample=fixture.sample,
        pages=page_scores,
        mean_text_cer=mean_cer,
        mean_text_recall=mean_recall,
        mean_keyword_recall=kr,
        overall_keyword_recall=kr,
        passed=passed,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# SHA256 helper (used by build_golden_ocr.py to populate the manifest)
# ---------------------------------------------------------------------------


def sha256_of_file(path: str | Path) -> str:
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


__all__ = [
    "GoldenSample",
    "PageGroundTruth",
    "GoldenFixture",
    "PageScore",
    "FixtureScore",
    "DEFAULT_GATES",
    "load_manifest",
    "load_fixture",
    "load_all_fixtures",
    "character_error_rate",
    "word_recall",
    "keyword_recall",
    "score_fixture",
    "sha256_of_file",
]
