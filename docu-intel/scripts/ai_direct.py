#!/usr/bin/env python3
"""Direct AI queries + search test."""
import json, time, requests

BASE = "http://localhost:8000/api/v1"
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
TOKEN = r.json()["access_token"]
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def api(method, path, data=None, timeout=180):
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


# Reprocess needs_review docs
print("--- Reprocesando needs_review ---")
needs_review = []
for did in range(8428, 8600):
    d = api("GET", f"/documents/{did}")
    if d and d.get("status") == "needs_review":
        needs_review.append(did)
print(f"  {len(needs_review)} documentos en needs_review")
if needs_review:
    for i in range(0, len(needs_review), 50):
        chunk = needs_review[i:i+50]
        r = api("POST", "/documents/reprocess-bulk", {"ids": chunk, "mode": "full", "limit": 50})
        if r:
            print(f"  Lote {i//50+1}: enqueued={r.get('enqueued',0)}")

# Wait briefly
print("\n  Esperando 60s...")
time.sleep(60)

# AI Queries
print("\n=== CONSULTAS IA ===")
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
    "Resumen ejecutivo: de que trata la documentacion?",
]
ai_results = []
for q in questions:
    print(f"\nP: {q}")
    r = api("POST", "/ai/ask", {"question": q}, timeout=240)
    if r:
        answer = r.get("answer", "")
        conf = r.get("confidence", 0)
        sources = r.get("sources", [])
        n_src = len(sources) if sources else 0
        print(f"R (conf={conf:.3f}, fuentes={n_src}): {answer[:450]}")
        ai_results.append({"q": q, "a": answer, "confidence": conf, "sources": n_src})
    else:
        print("SIN RESPUESTA")
        ai_results.append({"q": q, "a": "SIN RESPUESTA", "confidence": 0, "sources": 0})
    time.sleep(2)

# Search
print("\n=== BUSQUEDA ===")
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

# Summary
print("\n" + "=" * 60)
print("RESUMEN")
print("=" * 60)
ai_ok = sum(1 for r in ai_results if r["a"] != "SIN RESPUESTA")
print(f"IA responde: {ai_ok}/{len(ai_results)}")
avg_conf = sum(r["confidence"] for r in ai_results) / max(len(ai_results), 1)
print(f"Confianza media IA: {avg_conf:.3f}")
avg_src = sum(r["sources"] for r in ai_results) / max(len(ai_results), 1)
print(f"Fuentes promedio: {avg_src:.1f}")
total_hyb = sum(v["hybrid"] for v in search_results.values())
print(f"Busqueda hibrida: {total_hyb} hits en 4 queries")
