#!/usr/bin/env python3
"""Test script: upload 40 diverse docs, monitor processing, query AI."""
import json
import os
import sys
import time
import random
import subprocess
from pathlib import Path

import requests

BASE = "http://localhost:8000/api/v1"
EMAIL = "admin@local"
PASSWORD = "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"
TOKEN = None
RESULTS_DIR = Path(r"C:\Users\Usuario\Desktop\OCR\OCR\docu-intel\scripts\test_results")
RESULTS_DIR.mkdir(exist_ok=True)


def api(method, path, data=None, files=None, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{BASE}{path}"
    try:
        if files:
            resp = requests.post(url, files=files, headers=headers, timeout=300)
        elif data is not None:
            headers["Content-Type"] = "application/json"
            resp = requests.request(method, url, json=data, headers=headers, timeout=300)
        else:
            resp = requests.request(method, url, headers=headers, timeout=300)
        if resp.status_code >= 400:
            print(f"  HTTP {resp.status_code}: {resp.text[:300]}")
            return None
        return resp.json()
    except Exception as e:
        print(f"  Error: {e}")
        return None


def login():
    global TOKEN
    r = api("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    if r and "access_token" in r:
        TOKEN = r["access_token"]
        print(f"[OK] Logged in as {r['user']['name']} ({r['user']['role']})")
        return True
    print("[FAIL] Login failed")
    return False


def select_files():
    root = Path(r"C:\Users\Usuario\Desktop\TEST2025\2025")
    pdfs = list(root.rglob("*.pdf"))
    imgs = list(root.rglob("*.jpg")) + list(root.rglob("*.jpeg")) + list(root.rglob("*.png"))
    xls = list(root.rglob("*.xlsx")) + list(root.rglob("*.xls"))

    random.seed(42)
    selected = []
    selected += random.sample(pdfs, min(20, len(pdfs)))
    selected += random.sample(imgs, min(10, len(imgs)))
    selected += random.sample(xls, min(10, len(xls)))
    random.shuffle(selected)
    return selected[:40]


def upload_batch(files):
    print(f"\n=== UPLOADING {len(files)} FILES ===")
    uploaded = []
    for i in range(0, len(files), 5):
        batch = files[i : i + 5]
        file_list = [("files", (f.name, open(f, "rb"), "application/octet-stream")) for f in batch]
        url = f"{BASE}/documents/upload/batch"
        headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
        try:
            resp = requests.post(url, files=file_list, headers=headers, timeout=300)
            if resp.status_code == 200:
                r = resp.json()
                up = r.get("uploaded", 0)
                dup = r.get("duplicates", 0)
                fail = r.get("failed", 0)
                print(f"  Batch {i // 5 + 1}: uploaded={up} dup={dup} fail={fail}")
                for doc in r.get("documents", []):
                    uploaded.append(doc)
            else:
                print(f"  Batch {i // 5 + 1}: HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"  Batch {i // 5 + 1}: Error: {e}")
        finally:
            for _, (_, fh, _) in file_list:
                fh.close()
        time.sleep(0.5)
    return uploaded


def monitor_processing(doc_ids, max_wait=900):
    print(f"\n=== MONITORING {len(doc_ids)} DOCUMENTS (max {max_wait}s) ===")
    start = time.time()
    statuses = {}
    while time.time() - start < max_wait:
        statuses = {}
        problem_docs = []
        for did in doc_ids:
            r = api("GET", f"/documents/{did}", token=TOKEN)
            if r:
                s = r.get("status", "unknown")
                statuses[s] = statuses.get(s, 0) + 1
                if s in ("needs_review", "failed"):
                    problem_docs.append(f"  id={did} {r.get('original_filename','?')[:40]} status={s}")
        pending = statuses.get("pending", 0) + statuses.get("processing", 0)
        elapsed = int(time.time() - start)
        print(f"  [{elapsed}s] {statuses}")
        for d in problem_docs:
            print(d)
        if pending == 0:
            print("  All documents finished processing!")
            return statuses
        time.sleep(20)
    print("  Timeout reached")
    return statuses


def query_ai(questions):
    print(f"\n=== AI QUERIES ({len(questions)} questions) ===")
    results = []
    for q in questions:
        print(f"\n  Q: {q}")
        r = api("POST", "/ai/ask", {"question": q}, token=TOKEN)
        if r:
            answer = r.get("answer", str(r)[:500])
            confidence = r.get("confidence", "?")
            sources = r.get("sources", [])
            print(f"  A (conf={confidence}): {answer[:400]}")
            if sources:
                print(f"  Sources: {len(sources)} items")
            results.append({"q": q, "a": answer, "confidence": confidence, "sources": len(sources) if sources else 0})
        else:
            print("  [NO RESPONSE]")
            results.append({"q": q, "a": "NO RESPONSE", "confidence": 0, "sources": 0})
        time.sleep(2)
    return results


def check_search():
    print(f"\n=== SEARCH TEST ===")
    queries = ["presupuesto cortinas", "hotel mallorca", "factura proveedor", "tapiceria hotel"]
    all_results = {}
    for q in queries:
        r = api("GET", f"/search/text?q={q}&limit=3", token=TOKEN)
        text_count = len(r) if r else 0
        r2 = api("POST", "/search/semantic", {"query": q, "limit": 3}, token=TOKEN)
        sem_count = len(r2) if r2 else 0
        r3 = api("POST", "/search/hybrid", {"query": q, "limit": 3}, token=TOKEN)
        hyb_count = len(r3) if r3 else 0
        print(f"  '{q}': text={text_count} semantic={sem_count} hybrid={hyb_count}")
        all_results[q] = {"text": text_count, "semantic": sem_count, "hybrid": hyb_count}
    return all_results


def check_containers():
    print(f"\n=== CONTAINER & CODE STATUS ===")
    # Check container health
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}: {{.Status}}"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            if "docu-intel" in line:
                print(f"  {line}")

    # Check backend git commit
    result2 = subprocess.run(
        ["docker", "exec", "docu-intel-backend-1", "bash", "-c",
         "cd /app && git log --oneline -1 2>/dev/null || echo 'no git'"],
        capture_output=True, text=True, timeout=30
    )
    print(f"  Backend commit: {result2.stdout.strip() if result2.returncode == 0 else 'unknown'}")

    # Check mounted code is current
    result3 = subprocess.run(
        ["docker", "exec", "docu-intel-backend-1", "bash", "-c",
         "stat -c '%Y %n' /app/app/api/router.py 2>/dev/null || echo 'no file'"],
        capture_output=True, text=True, timeout=30
    )
    if result3.returncode == 0:
        mtime = result3.stdout.strip().split()[0]
        import datetime
        dt = datetime.datetime.fromtimestamp(int(mtime))
        print(f"  Backend router.py mtime: {dt}")

    # Check frontend build
    result4 = subprocess.run(
        ["docker", "exec", "docu-intel-frontend-1", "ls", "-la", "/usr/share/nginx/html/"],
        capture_output=True, text=True, timeout=30
    )
    if result4.returncode == 0:
        lines = result4.stdout.strip().split("\n")
        print(f"  Frontend files: {len(lines)} entries")

    # Check worker active tasks
    result5 = subprocess.run(
        ["docker", "exec", "docu-intel-worker-fast-1", "celery",
         "-A", "app.workers.celery_app.celery_app", "inspect", "active", "-d",
         "worker-fast@worker-fast-1", "--timeout=5"],
        capture_output=True, text=True, timeout=30
    )
    if result5.returncode == 0:
        print(f"  Worker-fast active: {result5.stdout.strip()[:200]}")

    result6 = subprocess.run(
        ["docker", "exec", "docu-intel-worker-heavy-1", "celery",
         "-A", "app.workers.celery_app.celery_app", "inspect", "active", "-d",
         "worker-heavy@worker-heavy-1", "--timeout=5"],
        capture_output=True, text=True, timeout=30
    )
    if result6.returncode == 0:
        print(f"  Worker-heavy active: {result6.stdout.strip()[:200]}")

    # Check LLM server
    result7 = subprocess.run(
        ["docker", "exec", "docu-intel-backend-1", "python", "-c",
         "import urllib.request; r=urllib.request.urlopen('http://host.docker.internal:1234/v1/models', timeout=5); print(r.read().decode()[:300])"],
        capture_output=True, text=True, timeout=30
    )
    if result7.returncode == 0:
        print(f"  LLM models: {result7.stdout.strip()[:200]}")
    else:
        print(f"  LLM check: {result7.stderr.strip()[:200]}")


def main():
    print("=" * 60)
    print("DOCU-INTEL: 40-DOCUMENT TEST SUITE")
    print("=" * 60)

    if not login():
        sys.exit(1)

    files = select_files()
    print(f"\nSelected {len(files)} files:")
    for i, f in enumerate(files):
        size_kb = f.stat().st_size / 1024
        client = f.parent.parent.parent.name[:35]
        print(f"  {i + 1:2d}. [{f.suffix:5s}] {f.name[:55]:55s} ({size_kb:6.0f}KB) {client}")

    uploaded = upload_batch(files)
    doc_ids = [d["document_id"] for d in uploaded if d.get("document_id")]
    print(f"\nUploaded {len(doc_ids)} documents")

    if not doc_ids:
        print("No documents uploaded successfully.")
        print("Checking existing documents in system for AI testing...")
        r = api("GET", "/documents?limit=40&status=processed", token=TOKEN)
        if r:
            doc_ids = [d["id"] for d in r]
            print(f"Using {len(doc_ids)} existing processed documents for AI tests")

    if doc_ids:
        statuses = monitor_processing(doc_ids, max_wait=900)
    else:
        statuses = {}

    questions = [
        "Que tipos de documentos hay en el sistema y de que tratan?",
        "Cuantos presupuestos hay y para que clientes?",
        "Que hotels aparecen en los documentos procesados?",
        "Hay facturas de proveedores de textiles o cortinas? Cuales?",
        "Que materiales se mencionan en los presupuestos?",
        "Cuales son los precios mas habituales para cortinas?",
        "Hay albaranes de entrega? De que productos?",
        "Que empresas de decoracion aparecen como proveedoras?",
        "Que cantidades y medidas de cortinas se manejan?",
        "Hay documentos de proyectos de reforma hotelera? Que hotels?",
    ]
    ai_results = query_ai(questions)

    search_results = check_search()

    check_containers()

    report = {
        "files_selected": len(files),
        "uploaded": len(uploaded),
        "doc_ids": doc_ids[:50],
        "final_statuses": statuses,
        "ai_results": ai_results,
        "search_results": search_results,
    }
    report_path = RESULTS_DIR / "test_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nReport saved to {report_path}")

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Files selected: {len(files)}")
    print(f"Uploaded: {len(uploaded)}")
    print(f"Final statuses: {statuses}")
    ai_success = sum(1 for r in ai_results if r["a"] != "NO RESPONSE")
    print(f"AI responses: {ai_success}/{len(ai_results)}")
    avg_src = sum(r["sources"] for r in ai_results) / max(len(ai_results), 1)
    print(f"Avg sources per answer: {avg_src:.1f}")
    total_search = sum(v["hybrid"] for v in search_results.values())
    print(f"Hybrid search hits: {total_search}")


if __name__ == "__main__":
    main()
