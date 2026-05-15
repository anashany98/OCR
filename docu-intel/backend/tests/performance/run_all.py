import os
import sys
import json
import subprocess
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


def check_services():
    print("Checking services...")
    try:
        resp = requests.get(f"{BASE_URL}/docs", timeout=5)
        if resp.status_code == 200:
            print("  Backend: OK")
            return True
    except:
        pass
    print("  Backend: NOT AVAILABLE - start with 'docker compose up' first")
    return False


def run_test(script_name):
    print(f"\nRunning {script_name}...")
    try:
        result = subprocess.run(
            [sys.executable, script_name],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.stdout:
            print(result.stdout)
        if result.returncode != 0 and result.stderr:
            print(f"Error: {result.stderr}", file=sys.stderr)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT - {script_name} took too long")
        return False
    except Exception as e:
        print(f"  Error running {script_name}: {e}")
        return False


def generate_combined_report():
    results_dir = Path("results")
    all_results = {"timestamp": datetime.now().isoformat(), "tests": {}}

    for result_file in results_dir.glob("*.json"):
        try:
            with open(result_file) as f:
                data = json.load(f)
                test_name = data.get("test", result_file.stem)
                all_results["tests"][test_name] = data
        except Exception as e:
            print(f"Error reading {result_file}: {e}")

    report_path = results_dir / f"combined_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w") as f:
        json.dump(all_results, f, indent=2)

    print(f"\n{'='*60}")
    print("COMBINED REPORT SUMMARY")
    print(f"{'='*60}")

    for test_name, data in all_results["tests"].items():
        print(f"\n{test_name.upper()}:")
        if test_name == "ingestion":
            print(f"  Upload times: avg={data['upload_times']['avg']}s, p95={data['upload_times']['p95']}s")
        elif test_name == "search":
            for endpoint, stats in data.get("results", {}).items():
                print(f"  /search/{endpoint}: avg={stats['avg']}s, p95={stats['p95']}s, errors={stats['errors']}")
        elif test_name == "sustained_load":
            for endpoint, stats in data.get("endpoints", {}).items():
                print(f"  {endpoint}: {stats['total_requests']} reqs, {stats['actual_rps']} rps, p95={stats['p95_latency']}s")

    print(f"\nFull report saved to: {report_path}")
    return all_results


def main():
    print("="*60)
    print("Docu-Intel Performance Test Suite")
    print("="*60)

    if not check_services():
        sys.exit(1)

    os.chdir(Path(__file__).parent)

    scripts = ["test_ingestion.py", "test_search.py", "test_api_sustained.py"]
    passed = []
    failed = []

    for script in scripts:
        if run_test(script):
            passed.append(script)
        else:
            failed.append(script)

    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")
    print(f"Passed: {len(passed)}/{len(scripts)}")
    for s in passed:
        print(f"  OK: {s}")
    if failed:
        print(f"Failed: {len(failed)}/{len(scripts)}")
        for s in failed:
            print(f"  FAIL: {s}")

    generate_combined_report()


if __name__ == "__main__":
    main()
