"""End-to-end test: process an image through the full pipeline."""
import requests, time

BASE = "http://localhost:8000/api/v1"
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
TOKEN = r.json()["access_token"]
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# Pick doc 8397 (WhatsApp image, OCR=0)
doc_id = 8397

# Reprocess it
r = requests.post(f"{BASE}/documents/reprocess-bulk", json={"ids": [doc_id], "mode": "full"}, headers=HDR, timeout=30)
print(f"Reprocess: {r.json()}")

# Wait for processing
print("Waiting for processing...")
for i in range(30):
    time.sleep(10)
    d = requests.get(f"{BASE}/documents/{doc_id}", headers=HDR).json()
    status = d.get("status")
    print(f"  [{(i+1)*10}s] status={status}")
    if status in ("processed", "needs_review"):
        break

# Check result
d = requests.get(f"{BASE}/documents/{doc_id}", headers=HDR).json()
print(f"\nResult:")
print(f"  status: {d.get('status')}")
print(f"  confidence: {d.get('confidence')}")
print(f"  page_count: {d.get('page_count')}")

pages = requests.get(f"{BASE}/documents/{doc_id}/pages", headers=HDR).json()
for p in pages:
    print(f"  page {p.get('page_number')}: ocr_confidence={p.get('ocr_confidence')} engine={p.get('ocr_engine')} text_len={len(p.get('extracted_text','') or '')}")

blocks = requests.get(f"{BASE}/documents/{doc_id}/blocks", headers=HDR).json()
print(f"  blocks: {len(blocks)}")
for b in blocks[:3]:
    print(f"    type={b.get('block_type')} text={len(b.get('text','') or '')} chars source={b.get('source_engine')}")
    if b.get('text'):
        print(f"    preview: {b['text'][:200]}")
