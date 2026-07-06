#!/usr/bin/env python3
import json, urllib.request, urllib.error

BASE = "http://localhost:8000/api/v1"

# Login
data = json.dumps({"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"}).encode()
req = urllib.request.Request(f"{BASE}/auth/login", data=data, headers={"Content-Type": "application/json"})
resp = urllib.request.urlopen(req)
r = json.loads(resp.read().decode())
token = r["access_token"]
print(f"Token: {token[:30]}...")

# Test: simple GET with Bearer
req2 = urllib.request.Request(f"{BASE}/documents?limit=1", headers={"Authorization": f"Bearer {token}"})
try:
    resp2 = urllib.request.urlopen(req2)
    print(f"GET OK: {resp2.read().decode()[:200]}")
except urllib.error.HTTPError as e:
    print(f"GET FAIL: {e.code} {e.read().decode()[:200]}")

# Test: upload with Bearer token
boundary = "----TestBoundary123"
body = b"--" + boundary.encode() + b"\r\n"
body += b'Content-Disposition: form-data; name="files"; filename="test.pdf"\r\n'
body += b"Content-Type: application/pdf\r\n\r\n"
body += b"%PDF-1.4 test content here"
body += b"\r\n--" + boundary.encode() + b"--\r\n"

req3 = urllib.request.Request(
    f"{BASE}/documents/upload",
    data=body,
    headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Authorization": f"Bearer {token}",
    },
    method="POST",
)
try:
    resp3 = urllib.request.urlopen(req3)
    print(f"Upload OK: {resp3.read().decode()[:300]}")
except urllib.error.HTTPError as e:
    print(f"Upload FAIL: {e.code} {e.read().decode()[:300]}")
