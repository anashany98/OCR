"""Background monitor for document processing."""
import time
import subprocess
import json
from datetime import datetime
from pathlib import Path

LOG_FILE = Path(r"C:\Users\Usuario\Desktop\OCR\OCR\docu-intel\scripts\monitor_log.json")
START = time.time()

def check():
    result = subprocess.run(
        ["docker", "exec", "docu-intel-postgres-1", "psql", "-U", "app", "-d", "docuintel", "-t", "-A", "-c",
         "SELECT status, COUNT(*) FROM documents WHERE deleted_at IS NULL GROUP BY status ORDER BY COUNT(*) DESC;"],
        capture_output=True, encoding="utf-8", timeout=15
    )
    statuses = {}
    for line in result.stdout.strip().split("\n"):
        if "|" in line:
            parts = line.split("|")
            statuses[parts[0].strip()] = int(parts[1].strip())
    
    result2 = subprocess.run(
        ["docker", "exec", "docu-intel-postgres-1", "psql", "-U", "app", "-d", "docuintel", "-t", "-A", "-c",
         "SELECT status, COUNT(*) FROM extraction_jobs_2026_07 WHERE status IN ('pending','processing') GROUP BY status;"],
        capture_output=True, encoding="utf-8", timeout=15
    )
    jobs = {}
    for line in result2.stdout.strip().split("\n"):
        if "|" in line:
            parts = line.split("|")
            jobs[parts[0].strip()] = int(parts[1].strip())
    
    elapsed = int(time.time() - START)
    timestamp = datetime.now().isoformat()
    
    entry = {
        "time": timestamp,
        "elapsed_s": elapsed,
        "documents": statuses,
        "jobs": jobs,
    }
    return entry

print("Monitor started. Logging every 5 minutes...")
log = []
while True:
    try:
        entry = check()
        log.append(entry)
        print(f"[{entry['elapsed_s']}s] processed={entry['documents'].get('processed',0)} "
              f"needs_review={entry['documents'].get('needs_review',0)} "
              f"processing={entry['documents'].get('processing',0)} "
              f"pending_jobs={entry['jobs'].get('pending',0)}")
        with open(LOG_FILE, "w") as f:
            json.dump(log, f, indent=2)
    except Exception as e:
        print(f"Error: {e}")
    time.sleep(300)  # 5 minutes
