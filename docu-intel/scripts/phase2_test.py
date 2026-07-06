#!/usr/bin/env python3
"""Phase 2: reprocess remaining docs, run AI queries, check results."""
import json, time, subprocess, requests

BASE = "http://localhost:8000/api/v1"
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
TOKEN = r.json()["access_token"]
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def api(method, path, data=None, timeout=120):
    url = f"{BASE}{path}"
    try:
        if method == "GET":
            r = requests.get(url, headers=HDR, timeout=timeout)
        else:
            r = requests.post(url, json=data, headers=HDR, timeout=timeout)
        if r.status_code >= 400:
            return None
        return r.json()
    except:
        return None


# Step 1: Reprocess pending/needs_review docs from our batch
print("--- PASO 1: Reprocesar pendientes ---")
pending_ids = []
for did in range(8428, 8600):
    d = api("GET", f"/documents/{did}")
    if d and d.get("status") in ("pending", "needs_review"):
        pending_ids.append(did)
print(f"  Documentos para reprocesar: {len(pending_ids)}")

if pending_ids:
    # Process in chunks of 50
    for i in range(0, len(pending_ids), 50):
        chunk = pending_ids[i:i+50]
        r = api("POST", "/documents/reprocess-bulk", {"ids": chunk, "mode": "full", "limit": 50})
        if r:
            print(f"  Lote {i//50+1}: enqueued={r.get('enqueued',0)} skipped={r.get('skipped',0)}")

# Step 2: Wait for processing
print("\n--- PASO 2: Esperar procesamiento ---")
for iteration in range(60):
    time.sleep(20)
    statuses = {}
    for did in range(8428, 8600):
        d = api("GET", f"/documents/{did}")
        if d:
            s = d.get("status", "?")
            statuses[s] = statuses.get(s, 0) + 1
    pending = statuses.get("pending", 0) + statuses.get("processing", 0)
    processed = statuses.get("processed", 0)
    print(f"  [{(iteration+1)*20}s] processed={processed} pending={statuses.get('pending',0)} processing={statuses.get('processing',0)} needs_review={statuses.get('needs_review',0)}")
    if pending == 0:
        print("  ¡Todo procesado!")
        break

# Step 3: Confidence check
print("\n--- PASO 3: Comprobar confianza ---")
good_confs = []
low_confs = []
for did in range(8428, 8600):
    d = api("GET", f"/documents/{did}")
    if d and d.get("status") == "processed":
        conf = d.get("confidence", 0) or 0
        if conf >= 0.4:
            good_confs.append((did, conf, d.get("original_filename", "?")))
        else:
            low_confs.append((did, conf, d.get("original_filename", "?")))

print(f"  Confianza >= 0.4: {len(good_confs)} documentos")
print(f"  Confianza < 0.4: {len(low_confs)} documentos")
if good_confs:
    avg = sum(c[1] for c in good_confs) / len(good_confs)
    print(f"  Media confianza buena: {avg:.3f}")
    for did, conf, name in good_confs[:5]:
        print(f"    {did}: {conf:.3f} {name[:40]}")

# Step 4: AI Queries
print("\n--- PASO 4: Consultas IA ---")
questions = [
    "Que tipos de documentos hay en el sistema? Describe su contenido.",
    "Cuantos presupuestos hay? Para que clientes y que hotels?",
    "Que empresas proveedoras de textiles o decoracion aparecen?",
    "Hay facturas? De que proveedores y por que importes?",
    "Que materiales se mencionan (cortinas, tapiceria, mobiliario)?",
    "Hay albaranes de entrega? De que productos?",
    "Que proyectos de reforma hotelera hay documentados?",
    "Que medidas y cantidades de productos se manejan?",
    "Que precios o rangos de precios aparecen?",
    "Resumen ejecutivo: de que trata la documentacion de este lote?",
]
ai_results = []
for q in questions:
    print(f"\n  P: {q}")
    r = api("POST", "/ai/ask", {"question": q}, timeout=180)
    if r:
        answer = r.get("answer", "")
        conf = r.get("confidence", 0)
        sources = r.get("sources", [])
        n_src = len(sources) if sources else 0
        print(f"  R (conf={conf:.3f}, fuentes={n_src}): {answer[:400]}")
        ai_results.append({"q": q, "a": answer, "confidence": conf, "sources": n_src})
    else:
        print("  SIN RESPUESTA")
        ai_results.append({"q": q, "a": "SIN RESPUESTA", "confidence": 0, "sources": 0})
    time.sleep(3)

# Step 5: Search test
print("\n--- PASO 5: Busqueda ---")
search_results = {}
for q in ["presupuesto cortinas hotel", "factura proveedor decoracion", "albaran entrega mobiliario", "reforma hotelera ibiza"]:
    t = api("GET", f"/search/text?q={q}&limit=5", timeout=30)
    s = api("POST", "/search/semantic", {"query": q, "limit": 5}, timeout=30)
    h = api("POST", "/search/hybrid", {"query": q, "limit": 5}, timeout=30)
    tn = len(t) if t else 0
    sn = len(s) if s else 0
    hn = len(h) if h else 0
    print(f"  '{q}': texto={tn} semantico={sn} hibrido={hn}")
    search_results[q] = {"text": tn, "semantic": sn, "hybrid": hn}

# Step 6: System health
print("\n--- PASO 6: Estado del sistema ---")
r = subprocess.run(["docker", "ps", "--format", "{{.Names}}: {{.Status}}"], capture_output=True, encoding="utf-8", timeout=30)
for line in r.stdout.strip().split("\n"):
    if "docu-intel" in line:
        print(f"  {line}")

r2 = subprocess.run(["docker", "exec", "docu-intel-postgres-1", "psql", "-U", "app", "-d", "docuintel", "-t", "-A", "-c",
    "SELECT status, COUNT(*) FROM documents GROUP BY status ORDER BY COUNT(*) DESC;"],
    capture_output=True, encoding="utf-8", timeout=15)
print(f"  Docs totales:")
for line in r2.stdout.strip().split("\n"):
    if line.strip():
        print(f"    {line}")

# Summary
print("\n" + "=" * 60)
print("RESUMEN FINAL")
print("=" * 60)
ai_ok = sum(1 for r in ai_results if r["a"] != "SIN RESPUESTA")
print(f"IA responde: {ai_ok}/{len(ai_results)}")
if good_confs:
    print(f"Confianza media OCR: {sum(c[1] for c in good_confs)/len(good_confs):.3f}")
avg_src = sum(r["sources"] for r in ai_results) / max(len(ai_results), 1)
print(f"Fuentes promedio por respuesta: {avg_src:.1f}")
total_hyb = sum(v["hybrid"] for v in search_results.values())
print(f"Busqueda hibrida: {total_hyb} hits en 4 queries")
