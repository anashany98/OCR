#!/usr/bin/env python3
import requests, json, time

BASE = "http://localhost:8000/api/v1"
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

statuses = {}
pending = []
for did in range(8388, 8428):
    r = requests.get(f"{BASE}/documents/{did}", headers=headers, timeout=10)
    if r.status_code == 200:
        d = r.json()
        s = d.get("status", "?")
        statuses[s] = statuses.get(s, 0) + 1
        if s in ("pending", "needs_review"):
            pending.append(did)
print(f"Statuses: {statuses}")
print(f"Pending/review: {len(pending)} docs")

if pending:
    r = requests.post(f"{BASE}/documents/reprocess-bulk", json={"ids": pending, "mode": "full", "limit": 50}, headers=headers, timeout=30)
    print(f"Reprocess: {r.json()}")

    # Wait for processing
    for i in range(30):
        time.sleep(20)
        s2 = {}
        for did in pending[:5]:
            r2 = requests.get(f"{BASE}/documents/{did}", headers=headers, timeout=10)
            if r2.status_code == 200:
                st = r2.json().get("status", "?")
                s2[st] = s2.get(st, 0) + 1
        print(f"  [{(i+1)*20}s] sample: {s2}")
        if s2.get("processing", 0) == 0 and s2.get("pending", 0) == 0:
            break
