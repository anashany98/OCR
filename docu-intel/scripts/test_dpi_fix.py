import requests, time

BASE = "http://localhost:8000/api/v1"
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
TOKEN = r.json()["access_token"]
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

r = requests.post(f"{BASE}/documents/reprocess-bulk", json={"ids": [1333], "mode": "full"}, headers=HDR, timeout=30)
print(f"Enqueue: {r.json()}")

time.sleep(20)

d = requests.get(f"{BASE}/documents/1333", headers=HDR).json()
print(f"Status: {d.get('status')}")
print(f"Confidence: {d.get('confidence')}")

pages = requests.get(f"{BASE}/documents/1333/pages", headers=HDR).json()
for p in pages:
    txt = p.get("extracted_text", "") or ""
    print(f"Page {p.get('page_number')}: ocr_conf={p.get('ocr_confidence')} engine={p.get('ocr_engine')} text_len={len(txt)}")
    if txt:
        print(f"  Text: {txt[:200]}")
