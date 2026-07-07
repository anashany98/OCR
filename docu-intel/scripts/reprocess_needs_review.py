"""Dispatch reprocess for all needs_review documents."""
import requests, time, subprocess

BASE = "http://localhost:8000/api/v1"
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
TOKEN = r.json()["access_token"]
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# Get needs_review doc IDs
result = subprocess.run(
    ["docker", "exec", "docu-intel-postgres-1", "psql", "-U", "app", "-d", "docuintel", "-t", "-A", "-c",
     "SELECT id FROM documents WHERE status='needs_review' AND deleted_at IS NULL ORDER BY id;"],
    capture_output=True, encoding="utf-8", timeout=30
)
doc_ids = [int(x.strip()) for x in result.stdout.strip().split("\n") if x.strip().isdigit()]
print(f"Documents to reprocess: {len(doc_ids)}")

# Enqueue in batches of 50
for i in range(0, len(doc_ids), 50):
    batch = doc_ids[i:i+50]
    r = requests.post(f"{BASE}/documents/reprocess-bulk", json={"ids": batch, "mode": "full", "limit": 50}, headers=HDR, timeout=60)
    if r.status_code == 200:
        data = r.json()
        print(f"  Batch {i//50+1}: enqueued={data.get('enqueued',0)}")
    else:
        print(f"  Batch {i//50+1}: HTTP {r.status_code}")

# Dispatch to Celery
print("\nDispatching to Celery...")
r2 = requests.get(f"{BASE}/admin/system/health", headers=HDR, timeout=30)

# Manual dispatch
docker_result = subprocess.run(
    ["docker", "exec", "docu-intel-backend-1", "bash", "-c",
     "cd /app && PYTHONPATH=/app python -c \""
     "from app.database.session import SessionLocal; "
     "from app.models import ExtractionJob, Document; "
     "from app.workers.tasks import process_document_task; "
     "from app.workers.routing import queue_for_document; "
     "db = SessionLocal(); "
     "pending = db.query(ExtractionJob).filter(ExtractionJob.status == 'pending').all(); "
     "print(f'Pending jobs: {len(pending)}'); "
     "dispatched = 0; "
     "for job in pending: "
     "    doc = db.get(Document, job.document_id); "
     "    if doc: "
     "        queue = queue_for_document(doc, job.job_type); "
     "        process_document_task.apply_async(args=(doc.id, job.id), queue=queue); "
     "        dispatched += 1; "
     "print(f'Dispatched: {dispatched}'); "
     "db.close()\""],
    capture_output=True, encoding="utf-8", timeout=60
)
print(docker_result.stdout)

# Monitor
print("\nMonitoring...")
start = time.time()
for iteration in range(90):
    time.sleep(30)
    result2 = subprocess.run(
        ["docker", "exec", "docu-intel-postgres-1", "psql", "-U", "app", "-d", "docuintel", "-t", "-A", "-c",
         "SELECT status, COUNT(*) FROM extraction_jobs_2026_07 WHERE status IN ('pending','processing') GROUP BY status;"],
        capture_output=True, encoding="utf-8", timeout=15
    )
    lines = result2.stdout.strip().split("\n")
    pending = 0
    processing = 0
    for line in lines:
        if "pending" in line:
            pending = int(line.split("|")[1].strip())
        elif "processing" in line:
            processing = int(line.split("|")[1].strip())
    elapsed = int(time.time() - start)
    print(f"  [{elapsed}s] pending={pending} processing={processing}")
    if pending == 0 and processing == 0:
        print("  All done!")
        break

# Final status
result3 = subprocess.run(
    ["docker", "exec", "docu-intel-postgres-1", "psql", "-U", "app", "-d", "docuintel", "-t", "-A", "-c",
     "SELECT status, COUNT(*) FROM documents WHERE deleted_at IS NULL GROUP BY status ORDER BY COUNT(*) DESC;"],
    capture_output=True, encoding="utf-8", timeout=15
)
print(f"\nFinal status:")
print(result3.stdout)
