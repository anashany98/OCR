#!/usr/bin/env python3
"""Reprocess stuck documents and run AI queries."""
import json
import time
import requests

BASE = "http://localhost:8000/api/v1"
TOKEN = None

def login():
    global TOKEN
    r = requests.post(f"{BASE}/auth/login", json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
    TOKEN = r.json()["access_token"]
    print(f"Logged in")

def api(method, path, data=None):
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    url = f"{BASE}{path}"
    if method == "GET":
        r = requests.get(url, headers=headers, timeout=60)
    else:
        r = requests.post(url, json=data, headers=headers, timeout=60)
    return r.json()

def main():
    login()

    # Reprocess stuck docs
    stuck_ids = [8388,8389,8390,8391,8392,8393,8394,8395,8396,8397,8398,8399,
                 8401,8402,8403,8405,8407,8408,8409,8410,8412,8413]
    print(f"\nReprocessing {len(stuck_ids)} documents...")
    r = api("POST", "/documents/reprocess-bulk", {"ids": stuck_ids, "mode": "full", "limit": 50})
    print(f"Reprocess result: {r}")

    # Wait for processing
    print("\nWaiting for processing...")
    for i in range(30):
        time.sleep(20)
        statuses = {}
        for did in stuck_ids[:5]:
            doc = api("GET", f"/documents/{did}")
            s = doc.get("status", "unknown")
            statuses[s] = statuses.get(s, 0) + 1
        print(f"  [{(i+1)*20}s] sample: {statuses}")
        if statuses.get("processing", 0) == 0 and statuses.get("pending", 0) == 0:
            break

    # Check final status
    print("\nFinal status check:")
    all_statuses = {}
    for did in stuck_ids:
        doc = api("GET", f"/documents/{did}")
        s = doc.get("status", "unknown")
        all_statuses[s] = all_statuses.get(s, 0) + 1
    print(f"  {all_statuses}")

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
    for q in questions:
        print(f"\nQ: {q}")
        r = api("POST", "/ai/ask", {"question": q})
        if r:
            answer = r.get("answer", str(r)[:500])
            conf = r.get("confidence", "?")
            sources = r.get("sources", [])
            print(f"A (conf={conf}): {answer[:400]}")
            if sources:
                print(f"Sources: {len(sources)} items")
        else:
            print("NO RESPONSE")

    # Search test
    print("\n" + "=" * 60)
    print("SEARCH TEST")
    print("=" * 60)
    for q in ["presupuesto cortinas", "hotel mallorca", "factura proveedor", "tapiceria hotel"]:
        r = api("GET", f"/search/text?q={q}&limit=3")
        text_n = len(r) if r else 0
        r2 = api("POST", "/search/semantic", {"query": q, "limit": 3})
        sem_n = len(r2) if r2 else 0
        r3 = api("POST", "/search/hybrid", {"query": q, "limit": 3})
        hyb_n = len(r3) if r3 else 0
        print(f"  '{q}': text={text_n} semantic={sem_n} hybrid={hyb_n}")

if __name__ == "__main__":
    main()
