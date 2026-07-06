import requests

BASE = "http://localhost:8000/api/v1"
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
T = r.json()["access_token"]
H = {"Authorization": f"Bearer {T}"}

# Test diverse documents from different clients
for did in [8580, 8500, 8450, 8350, 8300, 8200, 8100, 8000]:
    r = requests.get(f"{BASE}/admin/documents/{did}/graph", headers=H, timeout=30)
    if r.status_code == 200:
        g = r.json()
        nodes = g.get("nodes", [])
        edges = g.get("edges", [])
        # Get the source document name
        src = next((n for n in nodes if n.get("document_id") == did), {})
        fname = src.get("filename", "?")[:40]
        # Count unique presupuesto links
        presupuestos = set(e.get("label") for e in edges if e.get("relation") == "shared_reference" and e.get("label", "").isdigit())
        print(f"doc {did}: {len(nodes)} nodos, {len(edges)} aristas | {fname} | presupuestos: {presupuestos}")
    else:
        print(f"doc {did}: HTTP {r.status_code}")
