import os
import sys
import time
import statistics
import json
import threading
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


class LoadTester:
    def __init__(self, base_url, token, rps, duration_seconds):
        self.base_url = base_url
        self.token = token
        self.rps = rps
        self.duration = duration_seconds
        self.results = []
        self.running = False
        self.threads = []

    def make_request(self, endpoint):
        headers = {"Authorization": f"Bearer {self.token}"}
        start = time.time()
        try:
            if endpoint == "/documents":
                resp = requests.get(f"{self.base_url}{endpoint}", headers=headers, params={"limit": 50})
            elif endpoint == "/documents/1":
                resp = requests.get(f"{self.base_url}{endpoint}", headers=headers)
            elif endpoint == "/search/text":
                resp = requests.get(f"{self.base_url}{endpoint}", headers=headers, params={"q": "test", "limit": 10})
            else:
                resp = requests.get(f"{self.base_url}{endpoint}", headers=headers)
            status = resp.status_code
        except Exception as e:
            status = 0
            error = str(e)
        elapsed = time.time() - start
        return {"elapsed": elapsed, "status": status, "endpoint": endpoint, "timestamp": start}

    def worker(self, endpoint):
        delay = 1.0 / self.rps
        while self.running:
            result = self.make_request(endpoint)
            self.results.append(result)
            time.sleep(delay)

    def run(self):
        endpoints = ["/documents", "/documents/1", "/search/text"]
        self.running = True

        print(f"\nStarting sustained load test:")
        print(f"  Target: {self.rps} RPS per endpoint")
        print(f"  Duration: {self.duration} seconds")
        print(f"  Endpoints: {endpoints}")

        for endpoint in endpoints:
            t = threading.Thread(target=self.worker, args=(endpoint,))
            t.start()
            self.threads.append(t)

        print(f"\nRunning... ", end="", flush=True)
        for remaining in range(self.duration, 0, -1):
            time.sleep(1)
            if remaining % 10 == 0:
                print(f"{remaining}s ", end="", flush=True)
        print("done")

        self.running = False
        for t in self.threads:
            t.join()

        return self.generate_report()

    def generate_report(self):
        by_endpoint = {}
        for r in self.results:
            ep = r["endpoint"]
            if ep not in by_endpoint:
                by_endpoint[ep] = []
            by_endpoint[ep].append(r)

        report = {"test": "sustained_load", "timestamp": datetime.now().isoformat(), "rps_target": self.rps, "duration_seconds": self.duration, "endpoints": {}}

        print(f"\n{'='*60}")
        print("Sustained Load Results:")
        print(f"{'='*60}")

        for endpoint, results in by_endpoint.items():
            times = [r["elapsed"] for r in results]
            statuses = [r["status"] for r in results]
            errors = sum(1 for s in statuses if s >= 400)

            avg = statistics.mean(times) if times else 0
            p50 = statistics.quantiles(times, n=100)[49] if len(times) > 1 else times[0] if times else 0
            p95 = statistics.quantiles(times, n=100)[94] if len(times) > 1 else times[0] if times else 0
            actual_rps = len(results) / self.duration

            report["endpoints"][endpoint] = {
                "total_requests": len(results),
                "errors": errors,
                "error_rate": round(errors / len(results) * 100, 2) if results else 0,
                "actual_rps": round(actual_rps, 2),
                "avg_latency": round(avg, 3),
                "p50_latency": round(p50, 3),
                "p95_latency": round(p95, 3),
            }

            print(f"\n{endpoint}:")
            print(f"  Requests: {len(results)}, Errors: {errors} ({report['endpoints'][endpoint]['error_rate']}%)")
            print(f"  Actual RPS: {actual_rps:.2f}")
            print(f"  Latency - Avg: {avg:.3f}s, P50: {p50:.3f}s, P95: {p95:.3f}s")

        return report


def run_sustained_test(rps=5, duration=60):
    print(f"\n{'='*60}")
    print("TEST 3: Sustained API Load")
    print(f"{'='*60}")

    token = get_auth_token()
    tester = LoadTester(BASE_URL, token, rps=rps, duration_seconds=duration)
    return tester.run()


if __name__ == "__main__":
    rps = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    result = run_sustained_test(rps=rps, duration=duration)
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)
    with open(results_dir / f"sustained_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", "w") as f:
        json.dump(result, f, indent=2)
