import os
import sys
import time
import statistics
import json
from datetime import datetime
from pathlib import Path

import requests
from tqdm import tqdm

__test__ = False

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
EMAIL = os.getenv("TEST_EMAIL", "admin@local")
PASSWORD = os.getenv("TEST_PASSWORD", "admin123")


def get_auth_token():
    resp = requests.post(f"{BASE_URL}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    resp.raise_for_status()
    return resp.json()["access_token"]


def test_text_search(token, query, limit=20):
    headers = {"Authorization": f"Bearer {token}"}
    start = time.time()
    resp = requests.get(f"{BASE_URL}/search/text", headers=headers, params={"q": query, "limit": limit})
    elapsed = time.time() - start
    return {"elapsed": elapsed, "status": resp.status_code, "num_results": len(resp.json()) if resp.ok else 0}


def test_semantic_search(token, query, limit=10):
    headers = {"Authorization": f"Bearer {token}"}
    start = time.time()
    resp = requests.post(f"{BASE_URL}/search/semantic", headers=headers, json={"query": query, "limit": limit})
    elapsed = time.time() - start
    return {"elapsed": elapsed, "status": resp.status_code, "num_results": len(resp.json()) if resp.ok else 0}


def test_hybrid_search(token, query, limit=10):
    headers = {"Authorization": f"Bearer {token}"}
    start = time.time()
    resp = requests.post(f"{BASE_URL}/search/hybrid", headers=headers, json={"query": query, "limit": limit})
    elapsed = time.time() - start
    return {"elapsed": elapsed, "status": resp.status_code, "num_results": len(resp.json()) if resp.ok else 0}


QUERIES = [
    "presupuesto",
    "pedido",
    "factura",
    "plano",
    "habitacion",
    "cocina",
    "baño",
    "suelo",
    "pared",
    "ventana",
]


def run_search_test(requests_per_endpoint=50):
    print(f"\n{'='*60}")
    print("TEST 2: Search Endpoints Performance")
    print(f"{'='*60}")
    print(f"Requests per endpoint: {requests_per_endpoint}")

    token = get_auth_token()

    endpoints = {
        "text": (test_text_search, "GET"),
        "semantic": (test_semantic_search, "POST"),
        "hybrid": (test_hybrid_search, "POST"),
    }

    results = {}

    for name, (test_func, _) in endpoints.items():
        times = []
        errors = 0
        print(f"\nTesting /search/{name}...")
        with tqdm(total=requests_per_endpoint) as pbar:
            for i in range(requests_per_endpoint):
                query = QUERIES[i % len(QUERIES)]
                result = test_func(token, query)
                times.append(result["elapsed"])
                if result["status"] != 200:
                    errors += 1
                pbar.update(1)

        avg = statistics.mean(times)
        p50 = statistics.quantiles(times, n=100)[49] if len(times) > 1 else times[0]
        p95 = statistics.quantiles(times, n=100)[94] if len(times) > 1 else times[0]
        p99 = statistics.quantiles(times, n=100)[98] if len(times) > 1 else times[0]

        results[name] = {
            "requests": requests_per_endpoint,
            "errors": errors,
            "avg": round(avg, 3),
            "p50": round(p50, 3),
            "p95": round(p95, 3),
            "p99": round(p99, 3),
            "min": round(min(times), 3),
            "max": round(max(times), 3),
        }
        print(f"  Avg: {avg:.3f}s, P50: {p50:.3f}s, P95: {p95:.3f}s, P99: {p99:.3f}s")

    report = {
        "test": "search",
        "timestamp": datetime.now().isoformat(),
        "results": results,
    }

    print(f"\n{'='*60}")
    print("Search Summary:")
    for name, data in results.items():
        print(f"  /search/{name}: avg={data['avg']:.3f}s p95={data['p95']:.3f}s errors={data['errors']}")

    return report


if __name__ == "__main__":
    num_requests = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    result = run_search_test(num_requests)
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)
    with open(results_dir / f"search_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", "w") as f:
        json.dump(result, f, indent=2)
