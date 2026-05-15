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


def create_sample_pdf(output_path, size_kb=100):
    pdf_header = b"%PDF-1.4\n"
    pdf_footer = b"\n%%EOF"
    sample_content = b"Sample document content for testing. " * (size_kb * 5)
    with open(output_path, "wb") as f:
        f.write(pdf_header)
        f.write(b"1 0 obj << /Type /Catalog >> endobj\n")
        f.write(b"2 0 obj << /Length " + str(len(sample_content)).encode() + b" >> stream\n")
        f.write(sample_content)
        f.write(b"\nendstream endobj\n")
        f.write(pdf_footer)


def run_ingestion_test(num_documents=10, concurrent=3):
    print(f"\n{'='*60}")
    print("TEST 1: Document Ingestion Performance")
    print(f"{'='*60}")

    token = get_auth_token()
    sample_dir = Path("results/sample_docs")
    sample_dir.mkdir(parents=True, exist_ok=True)

    for i in range(num_documents):
        sample_file = sample_dir / f"sample_{i}.pdf"
        if not sample_file.exists():
            create_sample_pdf(sample_file, size_kb=100)

    results = []
    upload_times = []

    print("Uploading documents...")
    with tqdm(total=num_documents) as pbar:
        for i in range(num_documents):
            sample_file = sample_dir / f"sample_{i}.pdf"
            headers = {"Authorization": f"Bearer {token}"}
            start = time.time()
            with open(sample_file, "rb") as f:
                files = {"file": (sample_file.name, f, "application/octet-stream")}
                resp = requests.post(f"{BASE_URL}/documents/upload", headers=headers, files=files)
            elapsed = time.time() - start
            resp.raise_for_status()
            upload_times.append(elapsed)
            pbar.update(1)

    avg_upload = statistics.mean(upload_times) if upload_times else 0
    p50 = statistics.quantiles(upload_times, n=100)[49] if len(upload_times) > 1 else upload_times[0] if upload_times else 0
    p95 = statistics.quantiles(upload_times, n=100)[94] if len(upload_times) > 1 else upload_times[0] if upload_times else 0

    report = {
        "test": "ingestion",
        "timestamp": datetime.now().isoformat(),
        "num_documents": num_documents,
        "upload_times": {"avg": round(avg_upload, 3), "p50": round(p50, 3), "p95": round(p95, 3)},
    }

    print(f"\nUpload Times - Avg: {avg_upload:.3f}s, P50: {p50:.3f}s, P95: {p95:.3f}s")
    return report


if __name__ == "__main__":
    num_docs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    result = run_ingestion_test(num_docs)
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)
    with open(results_dir / f"ingestion_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", "w") as f:
        json.dump(result, f, indent=2)
