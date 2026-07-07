import requests

BASE = "http://localhost:8000/api/v1"
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
T = r.json()["access_token"]
H = {"Authorization": f"Bearer {T}"}

# Get document info
d = requests.get(f"{BASE}/documents/7567", headers=H).json()
print("=== DOCUMENTO 7567 ===")
print(f"Nombre: {d.get('original_filename')}")
print(f"Tipo: {d.get('document_type')}")
print(f"Estado: {d.get('status')}")
print(f"Confianza: {d.get('confidence')}")
print()

# Get entities
ents = requests.get(f"{BASE}/documents/7567/entities", headers=H).json()
print(f"Entidades: {len(ents)}")
for e in ents:
    print(f"  {e.get('entity_type')}: {e.get('entity_value')}")
print()

# Get graph
g = requests.get(f"{BASE}/admin/documents/7567/graph", headers=H).json()
nodes = g.get("nodes", [])
edges = g.get("edges", [])
print(f"=== GRAFO ===")
print(f"Nodos: {len(nodes)}")
print(f"Aristas: {len(edges)}")
print()

print("Nodos:")
for n in nodes:
    marker = " <<TU>>" if n.get("document_id") == 7567 else ""
    print(f"  [{n.get('document_id')}] {n.get('filename', '?')[:60]} ({n.get('document_type', '?')}){marker}")

print()
print("Aristas:")
for e in edges:
    print(f"  {e.get('from_document_id')} -> {e.get('to_document_id')} [{e.get('relation')}] label={e.get('label', '?')}")
