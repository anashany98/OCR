import requests

BASE = "http://localhost:8000/api/v1"
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
T = r.json()["access_token"]
H = {"Authorization": f"Bearer {T}"}

d = requests.get(f"{BASE}/documents/8539", headers=H).json()
print("=== DOCUMENT 8539 ===")
for k in ["original_filename", "status", "confidence", "page_count", "document_type", "error_message", "source_path", "extension", "file_size"]:
    print(f"  {k}: {d.get(k)}")

# Check pages
pages = requests.get(f"{BASE}/documents/8539/pages", headers=H).json()
print(f"\n  Pages: {len(pages)}")
for p in pages:
    print(f"    page {p.get('page_number')}: ocr_confidence={p.get('ocr_confidence')} text_len={len(p.get('extracted_text','') or '')}")

# Check blocks
blocks = requests.get(f"{BASE}/documents/8539/blocks", headers=H).json()
print(f"\n  Blocks: {len(blocks)}")
for b in blocks[:5]:
    print(f"    block {b.get('block_id')}: type={b.get('block_type')} text={len(b.get('text','') or '')} chars")

# Check entities
entities = requests.get(f"{BASE}/documents/8539/entities", headers=H).json()
print(f"\n  Entities: {len(entities)}")
for e in entities:
    print(f"    {e.get('entity_type')}: {e.get('entity_value')}")

# Check extraction jobs
import subprocess
result = subprocess.run(
    ["docker", "exec", "docu-intel-postgres-1", "psql", "-U", "app", "-d", "docuintel", "-t", "-A", "-c",
     "SELECT id, status, error_message, job_type FROM extraction_jobs_2026_07 WHERE document_id=8539;"],
    capture_output=True, encoding="utf-8", timeout=15
)
print(f"\n  Extraction jobs:")
print(f"    {result.stdout.strip()}")
