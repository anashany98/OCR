import requests, time

BASE = "http://localhost:8000/api/v1"
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
TOKEN = r.json()["access_token"]
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

questions = [
    "Que tipos de documentos hay en el sistema?",
    "Cuantos presupuestos hay? Para que clientes y hotels?",
    "Que empresas proveedoras de textiles o decoracion aparecen?",
    "Hay facturas? De que proveedores?",
    "Que materiales se mencionan?",
    "Hay albaranes de entrega?",
    "Que proyectos de reforma hotelera hay?",
    "Que medidas y cantidades se manejan?",
    "Que precios o rangos aparecen?",
    "Resumen ejecutivo de la documentacion?",
]

for q in questions:
    r = requests.post(f"{BASE}/ai/ask", json={"question": q}, headers=HDR, timeout=240)
    d = r.json()
    conf = d.get("confidence", 0)
    model = d.get("model_name", "?")
    src = len(d.get("sources", []))
    ans = d.get("answer", "")[:250]
    print(f"Q: {q}")
    print(f"  conf={conf:.3f}  model={model}  sources={src}")
    print(f"  A: {ans}")
    print()
    time.sleep(3)
