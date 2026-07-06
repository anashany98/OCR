import requests

BASE = "http://localhost:8000/api/v1"
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
T = r.json()["access_token"]
H = {"Authorization": f"Bearer {T}"}

# Test docs that HAVE entities
for did in [8543, 8544, 8541, 8533]:
    r = requests.get(f"{BASE}/admin/documents/{did}/graph", headers=H, timeout=30)
    if r.status_code == 200:
        g = r.json()
        nodes = g.get("nodes", [])
        edges = g.get("edges", [])
        print(f"doc {did}: {len(nodes)} nodos, {len(edges)} aristas")
        for n in nodes[:3]:
            print(f"  nodo: {n.get('filename', '?')[:50]} ({n.get('document_type', '?')})")
        for e in edges[:5]:
            print(f"  arista: {e.get('relation')} label={e.get('label', '?')}")
    else:
        print(f"doc {did}: HTTP {r.status_code}")
    print()
