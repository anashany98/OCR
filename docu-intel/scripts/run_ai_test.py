#!/usr/bin/env python3
"""AI queries + search test + container check."""
import json, time, subprocess, requests
from pathlib import Path

BASE = "http://localhost:8000/api/v1"
RESULTS_DIR = Path(r"C:\Users\Usuario\Desktop\OCR\OCR\docu-intel\scripts\test_results")
RESULTS_DIR.mkdir(exist_ok=True)

r = requests.post(f"{BASE}/auth/login", json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
TOKEN = r.json()["access_token"]
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def api(method, path, data=None):
    url = f"{BASE}{path}"
    try:
        if method == "GET":
            r = requests.get(url, headers=HEADERS, timeout=120)
        else:
            r = requests.post(url, json=data, headers=HEADERS, timeout=120)
        if r.status_code >= 400:
            return None
        return r.json()
    except Exception as e:
        print(f"  Error: {e}")
        return None

# Final status check
print("=" * 60)
print("FINAL DOCUMENT STATUS")
print("=" * 60)
statuses = {}
for did in range(8388, 8428):
    r = api("GET", f"/documents/{did}")
    if r:
        s = r.get("status", "?")
        statuses[s] = statuses.get(s, 0) + 1
print(f"  {statuses}")

# AI Queries
print("\n" + "=" * 60)
print("AI QUERIES")
print("=" * 60)
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
ai_results = []
for q in questions:
    print(f"\nQ: {q}")
    r = api("POST", "/ai/ask", {"question": q})
    if r:
        answer = r.get("answer", str(r)[:500])
        conf = r.get("confidence", "?")
        sources = r.get("sources", [])
        print(f"A (conf={conf}): {answer[:400]}")
        if sources:
            print(f"  Sources: {len(sources)} items")
        ai_results.append({"q": q, "a": answer, "confidence": conf, "sources": len(sources) if sources else 0})
    else:
        print("  NO RESPONSE")
        ai_results.append({"q": q, "a": "NO RESPONSE", "confidence": 0, "sources": 0})
    time.sleep(3)

# Search Test
print("\n" + "=" * 60)
print("SEARCH TEST")
print("=" * 60)
search_results = {}
for q in ["presupuesto cortinas", "hotel mallorca", "factura proveedor", "tapiceria hotel"]:
    r = api("GET", f"/search/text?q={q}&limit=3")
    text_n = len(r) if r else 0
    r2 = api("POST", "/search/semantic", {"query": q, "limit": 3})
    sem_n = len(r2) if r2 else 0
    r3 = api("POST", "/search/hybrid", {"query": q, "limit": 3})
    hyb_n = len(r3) if r3 else 0
    print(f"  '{q}': text={text_n} semantic={sem_n} hybrid={hyb_n}")
    search_results[q] = {"text": text_n, "semantic": sem_n, "hybrid": hyb_n}

# Container Check
print("\n" + "=" * 60)
print("CONTAINER & CODE STATUS")
print("=" * 60)
result = subprocess.run(["docker", "ps", "--format", "{{.Names}}: {{.Status}}"], capture_output=True, text=True, timeout=30)
for line in result.stdout.strip().split("\n"):
    if "docu-intel" in line:
        print(f"  {line}")

# Check git commit in backend
result2 = subprocess.run(["docker", "exec", "docu-intel-backend-1", "bash", "-c", "cd /app && git log --oneline -1 2>/dev/null || echo 'no git'"], capture_output=True, text=True, timeout=30)
print(f"  Backend git: {result2.stdout.strip()}")

# Check mount freshness
result3 = subprocess.run(["docker", "exec", "docu-intel-backend-1", "bash", "-c", "stat -c '%Y' /app/app/api/router.py 2>/dev/null"], capture_output=True, text=True, timeout=30)
if result3.returncode == 0:
    import datetime
    mtime = int(result3.stdout.strip())
    dt = datetime.datetime.fromtimestamp(mtime)
    print(f"  Backend router.py: {dt}")

# Check LLM server
result4 = subprocess.run(["docker", "exec", "docu-intel-backend-1", "python", "-c", "import urllib.request; r=urllib.request.urlopen('http://host.docker.internal:1234/v1/models', timeout=10); print(r.read().decode()[:200])"], capture_output=True, text=True, timeout=30)
if result4.returncode == 0:
    print(f"  LLM models: {result4.stdout.strip()[:150]}")
else:
    print(f"  LLM: {result4.stderr.strip()[:150]}")

# Check alembic version
result5 = subprocess.run(["docker", "exec", "docu-intel-postgres-1", "psql", "-U", "app", "-d", "docuintel", "-t", "-c", "SELECT version_num FROM alembic_version;"], capture_output=True, text=True, timeout=30)
print(f"  DB alembic: {result5.stdout.strip()}")

# Check total doc counts
result6 = subprocess.run(["docker", "exec", "docu-intel-postgres-1", "psql", "-U", "app", "-d", "docuintel", "-t", "-c", "SELECT status, COUNT(*) FROM documents GROUP BY status ORDER BY COUNT(*) DESC;"], capture_output=True, text=True, timeout=30)
print(f"  Total docs:\n{result6.stdout.strip()}")

# Save report
report = {
    "final_statuses": statuses,
    "ai_results": ai_results,
    "search_results": search_results,
    "ai_success": sum(1 for r in ai_results if r["a"] != "NO RESPONSE"),
    "ai_total": len(ai_results),
}
with open(RESULTS_DIR / "test_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f"\nReport saved to {RESULTS_DIR / 'test_report.json'}")

# Summary
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"AI: {report['ai_success']}/{report['ai_total']} responded")
avg_src = sum(r["sources"] for r in ai_results) / max(len(ai_results), 1)
print(f"Avg sources per answer: {avg_src:.1f}")
total_hyb = sum(v["hybrid"] for v in search_results.values())
print(f"Hybrid search hits: {total_hyb}")
print(f"DB alembic version: {result5.stdout.strip()}")
