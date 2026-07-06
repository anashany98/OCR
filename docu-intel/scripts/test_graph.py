import requests

BASE = "http://localhost:8000/api/v1"
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
T = r.json()["access_token"]
H = {"Authorization": f"Bearer {T}"}

# Test graph on several documents
for did in [8388, 8395, 8428, 8500, 8550, 8600]:
    r = requests.get(f"{BASE}/admin/documents/{did}/graph", headers=H, timeout=30)
    if r.status_code == 200:
        g = r.json()
        nodes = g.get("nodes", [])
        edges = g.get("edges", [])
        print(f"doc {did}: {len(nodes)} nodos, {len(edges)} aristas")
        for e in edges[:3]:
            print(f"  {e.get('relation')}: {e.get('label', '?')}")
    else:
        print(f"doc {did}: HTTP {r.status_code} {r.text[:100]}")
