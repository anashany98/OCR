"""Regression tests for the live AI benchmark harness.

The harness is deliberately outside the backend package, so load it by path
and exercise its pure planning and SSE parsing behaviour here.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "benchmark_ai_pipeline.py"
SPEC = importlib.util.spec_from_file_location("benchmark_ai_pipeline", SCRIPT)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def _scenario(name: str, **overrides):
    values = {
        "name": name,
        "question": f"question {name}",
        "category": "fact_extraction",
        "must_contain_facts": [],
        "must_not_contain": [],
        "must_cite_documents": [],
        "must_abstain": False,
        "expected_silence_marker": [],
    }
    values.update(overrides)
    return benchmark.Scenario(**values)


def test_request_plan_reuses_dependency_session_and_mode_for_cache_hit():
    parent = _scenario("exact", mode="exact_first")
    cache_repeat = _scenario(
        "cache_repeat", depends_on="exact", must_hit_cache=True, mode="hybrid"
    )

    plan = benchmark._request_plan([parent, cache_repeat])

    assert plan[0][1] == plan[1][1]
    assert plan[1][2] == "exact_first"


def test_request_plan_rejects_dependency_missing_from_selection():
    with pytest.raises(ValueError, match="must appear earlier"):
        benchmark._request_plan([_scenario("followup", depends_on="missing")])


def test_quality_requires_every_declared_fact_and_required_cache_hit():
    scenario = _scenario(
        "facts",
        must_contain_facts=[
            {"field": "first", "values": ["uno"]},
            {"field": "second", "values": ["dos"]},
        ],
        must_hit_cache=True,
    )

    assert benchmark._check_quality(scenario, "uno", [], cache_hit=True) == (
        False,
        "missing_required_fact:second",
    )
    assert benchmark._check_quality(scenario, "uno y dos", [], cache_hit=False) == (
        False,
        "cache_hit_required",
    )
    assert benchmark._check_quality(scenario, "uno y dos", [], cache_hit=True) == (True, None)


def test_quality_compares_document_ids_independently_of_json_number_type():
    scenario = _scenario("cited", must_cite_documents=[161394])

    assert benchmark._check_quality(
        scenario, "respuesta", [{"document_id": 161394}]
    ) == (True, None)


def test_parse_credentials_never_accepts_an_ambiguous_value():
    assert benchmark._parse_credentials(
        ["viewer@local=viewer-secret"],
        default_user="admin@local",
        default_password="admin-secret",
    ) == {"admin@local": "admin-secret", "viewer@local": "viewer-secret"}
    with pytest.raises(ValueError, match="EMAIL=CONTRASENA"):
        benchmark._parse_credentials(["viewer@local"], default_user="a", default_password="b")


def test_sse_request_carries_isolated_session_mode_and_cache_status():
    captured: dict = {}

    class FakeResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def iter_lines(self):
            return iter(
                [
                    "event: status",
                    'data: {"state":"cache","cache_hit":true}',
                    "event: end",
                    'data: {"answer":"respuesta", "sources":[{"document_id":7}], "cache_hit":true}',
                ]
            )

    class FakeHTTPClient:
        def stream(self, _method, _url, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

    client = benchmark.BenchmarkClient.__new__(benchmark.BenchmarkClient)
    client.base_url = "http://test"
    client._client = FakeHTTPClient()
    client._token = "token"
    scenario = _scenario("cached", question="same question", must_hit_cache=True)

    result = client.ask_stream(scenario, session_id="session-1", mode="exact_first")

    assert captured["json"] == {
        "question": "same question",
        "mode": "exact_first",
        "session_id": "session-1",
    }
    assert result.cache_hit is True
    assert result.quality_pass is True
