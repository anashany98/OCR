import requests, time, subprocess

BASE = "http://localhost:8000/api/v1"
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
TOKEN = r.json()["access_token"]
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# Get doc IDs with OCR=0
result = subprocess.run(
    ["docker", "exec", "docu-intel-postgres-1", "psql", "-U", "app", "-d", "docuintel", "-t", "-A", "-c",
     "SELECT DISTINCT d.id FROM document_pages dp JOIN documents d ON d.id = dp.document_id WHERE dp.ocr_confidence = 0 AND d.status != 'duplicate' AND d.deleted_at IS NULL ORDER BY d.id;"],
    capture_output=True, encoding="utf-8", timeout=30
)
doc_ids = [int(x.strip()) for x in result.stdout.strip().split("\n") if x.strip().isdigit()]
print(f"Documents with OCR=0: {len(doc_ids)}")

# Enqueue
for i in range(0, len(doc_ids), 50):
    batch = doc_ids[i:i+50]
    r = requests.post(f"{BASE}/documents/reprocess-bulk", json={"ids": batch, "mode": "full", "limit": 50}, headers=HDR, timeout=60)
    if r.status_code == 200:
        data = r.json()
        print(f"  Batch {i//50+1}: enqueued={data.get('enqueued',0)}")
    else:
        print(f"  Batch {i//50+1}: HTTP {r.status_code}")

print("\nMonitoring...")
start = time.time()
for iteration in range(60):
    time.sleep(30)
    result2 = subprocess.run(
        ["docker", "exec", "docu-intel-postgres-1", "psql", "-U", "app", "-d", "docuintel", "-t", "-A", "-c",
         "SELECT COUNT(DISTINCT d.id) FROM document_pages dp JOIN documents d ON d.id = dp.document_id WHERE dp.ocr_confidence = 0 AND d.status != 'duplicate' AND d.deleted_at IS NULL;"],
        capture_output=True, encoding="utf-8", timeout=15
    )
    remaining = result2.stdout.strip()
    elapsed = int(time.time() - start)
    print(f"  [{elapsed}s] OCR=0 remaining: {remaining}")
    if remaining == "0":
        print("  All done!")
        break
