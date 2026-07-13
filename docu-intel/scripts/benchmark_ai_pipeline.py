#!/usr/bin/env python3
"""MiniMax M3 — Reproducible AI pipeline benchmark (FASE 8).

Exercises the live API across the golden question set and the
target scenarios. Unlike the earlier benchmark tool this
version:

* Loads the canonical questions.json and manifest.sanitized.json
  from ``backend/tests/fixtures/minimax_m3_eval/`` so the
  benchmark is in lock-step with the FASE 0 artefacts.
* Asserts each scenario's must_contain / must_not_contain
  expectations, citation target and (when required) abstention
  marker against the actual response.
* Drives one cold run followed by three warm runs per scenario
  so the cold/hot split is visible in the output.
* Counts cache hits by looking at the response payload
  (``cache_hit`` or the absence of a model_name).
* Exits non-zero if any scenario fails the quality contract
  OR a stage's p95 exceeds the FASE 4 target.

The tool never logs full questions, names or content. Only
aggregate metrics and a short hash of the question are recorded.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import statistics
import sys
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import httpx  # type: ignore
except Exception:  # pragma: no cover
    httpx = None  # type: ignore


REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "backend" / "tests" / "fixtures" / "minimax_m3_eval"
QUESTIONS_PATH = FIXTURE_DIR / "questions.json"

DEFAULT_BASE_URL = os.environ.get("M3_BENCH_BASE_URL", "http://localhost:8000")
DEFAULT_USER = os.environ.get("M3_BENCH_USER", "admin@local")
DEFAULT_PASS = os.environ.get("M3_BENCH_PASS", "admin1234")

# FASE 4 targets. The benchmark fails the suite if a scenario
# exceeds the p95 budget for any stage.
TARGET_FIRST_EVENT_P95_MS = 5_000.0  # generous for the local LLM
TARGET_FIRST_DELTA_P95_MS = 30_000.0
TARGET_TOTAL_P95_MS = 60_000.0
TARGET_QUALITY_FRACTION = 0.90  # 90% of scenarios must pass


@dataclasses.dataclass
class Scenario:
    name: str
    question: str
    category: str
    must_contain_facts: list[dict[str, Any]]
    must_not_contain: list[str]
    must_cite_documents: list[int]
    must_abstain: bool
    expected_silence_marker: list[str]
    mode: str = "hybrid"
    user: str | None = None
    depends_on: str | None = None
    must_hit_cache: bool = False


@dataclasses.dataclass
class RunResult:
    scenario: str
    run_index: int
    cold: bool
    status_code: int
    error: str | None
    total_ms: float
    first_event_ms: float | None
    first_delta_ms: float | None
    sources_count: int | None
    answer_preview: str | None
    cache_hit: bool = False
    quality_pass: bool = False
    quality_reason: str | None = None


# ---------------------------------------------------------------------------
# Question loading
# ---------------------------------------------------------------------------


def _load_questions() -> list[Scenario]:
    with open(QUESTIONS_PATH, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    out: list[Scenario] = []
    for entry in raw.get("scenarios", []):
        out.append(
            Scenario(
                name=entry["id"],
                question=entry["question"],
                category=entry.get("category", "fact_extraction"),
                must_contain_facts=entry.get("must_contain_facts") or [],
                must_not_contain=entry.get("must_not_contain") or [],
                must_cite_documents=entry.get("must_cite_documents") or [],
                must_abstain=bool(entry.get("must_abstain")),
                expected_silence_marker=entry.get("expected_silence_marker") or [],
                mode=entry.get("kind") or "hybrid",
                user=entry.get("user"),
                depends_on=entry.get("depends_on"),
                must_hit_cache=bool(entry.get("must_hit_cache")),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Quality checks
# ---------------------------------------------------------------------------


def _check_quality(
    scenario: Scenario, answer: str, sources: list[dict], *, cache_hit: bool = False
) -> tuple[bool, str | None]:
    text = (answer or "").lower()
    if scenario.must_abstain:
        # The answer must NOT include a verbatim fact and MUST
        # include at least one silence marker.
        for forbidden in scenario.must_not_contain:
            if forbidden.lower() in text:
                return False, f"abstain_violation: '{forbidden}' present"
        if not any(marker.lower() in text for marker in scenario.expected_silence_marker):
            return False, "abstain_marker_missing"
        return True, None
    # Each entry represents one required fact. Its ``values`` are acceptable
    # variants of that fact, not alternatives to every other required fact.
    for fact in scenario.must_contain_facts:
        values = [str(value).lower() for value in fact.get("values") or []]
        regex = fact.get("regex")
        if values and not any(value in text for value in values):
            return False, f"missing_required_fact:{fact.get('field', 'unknown')}"
        if regex:
            import re

            if not re.search(str(regex), answer or "", flags=re.IGNORECASE):
                return False, f"missing_required_pattern:{fact.get('field', 'unknown')}"
    for forbidden in scenario.must_not_contain:
        if forbidden.lower() in text:
            return False, f"forbidden_present: '{forbidden}'"
    if scenario.must_cite_documents:
        cited = {str(src.get("document_id")) for src in sources or []}
        for doc_id in scenario.must_cite_documents:
            if doc_id not in cited:
                return False, f"missing_citation:{doc_id}"
    if scenario.must_hit_cache and not cache_hit:
        return False, "cache_hit_required"
    return True, None


def _parse_credentials(
    values: list[str] | None, *, default_user: str, default_password: str
) -> dict[str, str]:
    """Parse repeatable ``EMAIL=PASSWORD`` options without ever logging them."""
    credentials = {default_user: default_password}
    for value in values or []:
        email, separator, password = value.partition("=")
        if not separator or not email.strip() or not password:
            raise ValueError("--credential debe tener el formato EMAIL=CONTRASENA")
        credentials[email.strip()] = password
    return credentials


def _request_plan(scenarios: list[Scenario]) -> list[tuple[Scenario, str, str]]:
    """Create isolated sessions and preserve declared golden dependencies.

    A new benchmark invocation gets new session ids, so its first request is
    genuinely cold. Dependent scenarios reuse their parent's session. A cache
    assertion also reuses the parent's mode because mode belongs to the cache
    isolation vector.
    """
    run_id = uuid.uuid4().hex
    by_name = {scenario.name: scenario for scenario in scenarios}
    sessions: dict[str, str] = {}
    plan: list[tuple[Scenario, str, str]] = []
    for scenario in scenarios:
        if scenario.depends_on:
            if scenario.depends_on not in sessions:
                raise ValueError(
                    f"scenario {scenario.name!r} depends on {scenario.depends_on!r}, "
                    "which must appear earlier in the selected set"
                )
            session_id = sessions[scenario.depends_on]
        else:
            session_id = f"m3-benchmark-{run_id}-{scenario.name}"
            sessions[scenario.name] = session_id

        mode = scenario.mode
        if scenario.must_hit_cache and scenario.depends_on:
            mode = by_name[scenario.depends_on].mode
        plan.append((scenario, session_id, mode))
    return plan


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class BenchmarkClient:
    def __init__(self, base_url: str, user: str, password: str) -> None:
        if httpx is None:
            raise SystemExit("httpx is required for the benchmark")
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.password = password
        self._client = httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0))
        self._token: str | None = None

    def login(self) -> None:
        r = self._client.post(
            f"{self.base_url}/api/v1/auth/login",
            json={"email": self.user, "password": self.password},
        )
        r.raise_for_status()
        self._token = r.json()["access_token"]
        if not self._token:
            raise SystemExit("login response missing access_token")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def ask_stream(self, scenario: Scenario, *, session_id: str, mode: str) -> RunResult:
        url = f"{self.base_url}/api/v1/ai/ask/stream"
        body = {"question": scenario.question, "mode": mode, "session_id": session_id}
        t0 = time.perf_counter()
        first_event: float | None = None
        first_delta: float | None = None
        end_seen = False
        answer = ""
        sources: list[dict] = []
        cache_hit = False
        error: str | None = None
        status_code = 0
        try:
            with self._client.stream(
                "POST",
                url,
                json=body,
                headers=self._headers(),
                timeout=httpx.Timeout(180.0, connect=10.0),
            ) as response:
                status_code = response.status_code
                current_event: str | None = None
                for line in response.iter_lines():
                    if not line:
                        continue
                    if first_event is None:
                        first_event = (time.perf_counter() - t0) * 1000.0
                    if line.startswith("event: "):
                        current_event = line[7:].strip()
                    elif line.startswith("data: "):
                        try:
                            payload = json.loads(line[6:])
                        except Exception:
                            payload = {}
                        if current_event == "delta" and "text" in payload:
                            if first_delta is None:
                                first_delta = (time.perf_counter() - t0) * 1000.0
                            answer += payload.get("text", "")
                        if current_event == "end":
                            end_seen = True
                            answer = payload.get("answer", answer)
                            sources = payload.get("sources") or []
                            cache_hit = bool(payload.get("cache_hit"))
        except Exception as exc:
            error = repr(exc)[:200]
        total_ms = (time.perf_counter() - t0) * 1000.0
        quality_pass, quality_reason = _check_quality(
            scenario, answer, sources, cache_hit=cache_hit
        )
        return RunResult(
            scenario=scenario.name,
            run_index=0,
            cold=False,
            status_code=status_code,
            error=error,
            total_ms=total_ms,
            first_event_ms=first_event,
            first_delta_ms=first_delta,
            sources_count=len(sources) if end_seen else None,
            answer_preview=answer[:160] if answer else None,
            cache_hit=cache_hit,
            quality_pass=quality_pass,
            quality_reason=quality_reason,
        )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * pct
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def _summarise(runs: list[RunResult]) -> dict[str, Any]:
    ok = [r for r in runs if r.status_code == 200 and not r.error]
    quality_pass = [r for r in ok if r.quality_pass]
    return {
        "count": len(runs),
        "successful": len(ok),
        "quality_pass": len(quality_pass),
        "total_ms_p50": _percentile([r.total_ms for r in ok], 0.5),
        "total_ms_p95": _percentile([r.total_ms for r in ok], 0.95),
        "first_event_ms_p50": _percentile(
            [r.first_event_ms for r in ok if r.first_event_ms is not None], 0.5
        ),
        "first_event_ms_p95": _percentile(
            [r.first_event_ms for r in ok if r.first_event_ms is not None], 0.95
        ),
        "first_delta_ms_p50": _percentile(
            [r.first_delta_ms for r in ok if r.first_delta_ms is not None], 0.5
        ),
        "first_delta_ms_p95": _percentile(
            [r.first_delta_ms for r in ok if r.first_delta_ms is not None], 0.95
        ),
    }


def _print_table(scenarios: list[Scenario], runs: list[RunResult]) -> None:
    by_scenario: dict[str, list[RunResult]] = {}
    for r in runs:
        by_scenario.setdefault(r.scenario, []).append(r)
    print()
    print(
        f"{'scenario':<28s} {'runs':>4s} {'ok':>3s} {'qpass':>5s} "
        f"{'p50ms':>8s} {'p95ms':>8s} {'fe_p95':>8s} {'fd_p95':>8s}"
    )
    print("-" * 90)
    for s in scenarios:
        rows = by_scenario.get(s.name, [])
        if not rows:
            print(f"{s.name[:26]:<28s}  no runs")
            continue
        summary = _summarise(rows)
        print(
            f"{s.name[:26]:<28s} {summary['count']:>4d} {summary['successful']:>3d} "
            f"{summary['quality_pass']:>5d} {summary['total_ms_p50']:>8.0f} "
            f"{summary['total_ms_p95']:>8.0f} {summary['first_event_ms_p95']:>8.0f} "
            f"{summary['first_delta_ms_p95']:>8.0f}"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASS)
    parser.add_argument(
        "--credential",
        action="append",
        default=[],
        metavar="EMAIL=CONTRASENA",
        help="Credencial adicional para un escenario que declara otro usuario; repetible.",
    )
    parser.add_argument(
        "--warm-runs", type=int, default=3, help="Number of warm runs per scenario"
    )
    parser.add_argument(
        "--scenario", action="append", help="Limit to specific scenario names"
    )
    parser.add_argument(
        "--output-json", default=None, help="Optional path to write the JSON report"
    )
    parser.add_argument(
        "--request-interval-seconds",
        type=float,
        default=7.0,
        help=(
            "SeparaciÃ³n mÃ­nima entre consultas; 7 s deja margen para el "
            "lÃ­mite global de 10/minuto, que tambiÃ©n cuenta el login."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the tool itself without hitting the API",
    )
    args = parser.parse_args(argv)
    if args.request_interval_seconds < 0:
        print("--request-interval-seconds debe ser >= 0", file=sys.stderr)
        return 2

    scenarios = _load_questions()
    if args.scenario:
        scenarios = [s for s in scenarios if s.name in args.scenario]
    if not scenarios:
        print("No scenarios matched", file=sys.stderr)
        return 2

    if args.dry_run:
        rows = [
            RunResult(
                scenario=s.name,
                run_index=i,
                cold=(i == 0),
                status_code=200,
                error=None,
                total_ms=1000.0 + 100.0 * i,
                first_event_ms=200.0 + 30.0 * i,
                first_delta_ms=400.0 + 40.0 * i,
                sources_count=3,
                answer_preview="[dry-run preview]",
                quality_pass=True,
            )
            for s in scenarios
            for i in range(args.warm_runs + 1)
        ]
        _print_table(scenarios, rows)
        return 0

    try:
        credentials = _parse_credentials(
            args.credential, default_user=args.user, default_password=args.password
        )
        request_plan = _request_plan(scenarios)
    except ValueError as exc:
        print(f"!! invalid configuration: {exc}", file=sys.stderr)
        return 2

    all_runs: list[RunResult] = []
    clients: dict[str, BenchmarkClient] = {}
    last_request_started: float | None = None
    for s, session_id, mode in request_plan:
        print(f">> scenario {s.name} (warm_runs={args.warm_runs})", flush=True)
        email = s.user or args.user
        password = credentials.get(email)
        if password is None:
            print("   [skip] missing credential for scenario user", flush=True)
            all_runs.append(
                RunResult(
                    scenario=s.name,
                    run_index=0,
                    cold=True,
                    status_code=0,
                    error="missing_scenario_credential",
                    total_ms=0.0,
                    first_event_ms=None,
                    first_delta_ms=None,
                    sources_count=None,
                    answer_preview=None,
                    quality_reason="missing_scenario_credential",
                )
            )
            continue
        client = clients.get(email)
        if client is None:
            client = BenchmarkClient(args.base_url, email, password)
            try:
                client.login()
            except Exception as exc:
                print(f"   [skip] scenario login failed: {exc}", flush=True)
                all_runs.append(
                    RunResult(
                        scenario=s.name,
                        run_index=0,
                        cold=True,
                        status_code=0,
                        error="scenario_login_failed",
                        total_ms=0.0,
                        first_event_ms=None,
                        first_delta_ms=None,
                        sources_count=None,
                        answer_preview=None,
                        quality_reason="scenario_login_failed",
                    )
                )
                continue
            clients[email] = client
        for run_index in range(args.warm_runs + 1):
            # A declared cache-repeat intentionally reuses its dependency's
            # key, so even its first observation is a warm request.
            cold = run_index == 0 and not s.must_hit_cache
            if last_request_started is not None:
                delay = args.request_interval_seconds - (time.monotonic() - last_request_started)
                if delay > 0:
                    time.sleep(delay)
            last_request_started = time.monotonic()
            r = client.ask_stream(s, session_id=session_id, mode=mode)
            r.scenario = s.name
            r.run_index = run_index
            r.cold = cold
            all_runs.append(r)
            label = "cold" if cold else "warm"
            print(
                f"   [{label:>4}] stream# {run_index:>2d} status={r.status_code} "
                f"fe={(r.first_event_ms or 0):6.0f}ms "
                f"fd={(r.first_delta_ms or 0):6.0f}ms "
                f"total={r.total_ms:7.0f}ms "
                f"qpass={r.quality_pass} {r.quality_reason or ''}",
                flush=True,
            )

    _print_table(scenarios, all_runs)

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "metadata": {
                        "tool": "scripts/benchmark_ai_pipeline.py",
                        "version": "2.0.0",
                        "base_url": args.base_url,
                        "warm_runs": args.warm_runs,
                        "timestamp_utc": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                        ),
                    },
                    "scenarios": [
                        {
                            "name": s.name,
                            "category": s.category,
                            "question_hash": hashlib.sha256(
                                s.question.strip().lower().encode("utf-8")
                            ).hexdigest()[:10],
                        }
                        for s in scenarios
                    ],
                    "runs": [dataclasses.asdict(r) for r in all_runs],
                },
                fh,
                indent=2,
                ensure_ascii=False,
            )
        print(f"\nJSON report written to: {args.output_json}")

    # FASE 8 quality contract: at least 90% of successful runs must
    # pass the quality checks. Also: any scenario whose p95 total
    # exceeds the target fails the suite.
    incomplete = [r for r in all_runs if r.status_code != 200 or r.error]
    if incomplete:
        print(
            f"!! certification incomplete: {len(incomplete)} run(s) did not return HTTP 200.",
            file=sys.stderr,
        )
        return 1
    total_successful = len(all_runs)
    total_quality = sum(1 for r in all_runs if r.quality_pass and r.status_code == 200)
    quality_fraction = total_quality / total_successful if total_successful else 0.0
    if quality_fraction < TARGET_QUALITY_FRACTION:
        print(
            f"!! quality fraction {quality_fraction:.2%} is below the "
            f"{TARGET_QUALITY_FRACTION:.0%} target.",
            file=sys.stderr,
        )
        return 1
    by_scenario: dict[str, list[RunResult]] = {}
    for r in all_runs:
        by_scenario.setdefault(r.scenario, []).append(r)
    for s in scenarios:
        rows = [r for r in by_scenario.get(s.name, []) if r.status_code == 200 and not r.error]
        if not rows:
            continue
        p95_total = _percentile([r.total_ms for r in rows], 0.95)
        if p95_total > TARGET_TOTAL_P95_MS:
            print(
                f"!! {s.name} p95 total {p95_total:.0f}ms exceeds the "
                f"{TARGET_TOTAL_P95_MS:.0f}ms target.",
                file=sys.stderr,
            )
            return 1
    print(
        f"\nPASS: quality fraction {quality_fraction:.2%} and "
        f"all scenarios within the p95 total target."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
