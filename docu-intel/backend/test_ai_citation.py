"""Test AI citation behavior."""
from app.core.security import create_access_token
from fastapi.testclient import TestClient
from app.main import app

token = create_access_token("1")
client = TestClient(app)
resp = client.post(
    "/api/v1/ai/ask",
    json={"question": "¿Cuál es el total del presupuesto 1037872?", "mode": "hybrid"},
    headers={"Authorization": f"Bearer {token}"},
)
print("Status:", resp.status_code)
data = resp.json()
answer = data.get("answer", "")
print("Answer:", answer[:500])
print("Sources:", len(data.get("sources", [])))
for s in data.get("sources", []):
    print(f"  - Doc {s.get('document_id')}: pag {s.get('page_number')}")
