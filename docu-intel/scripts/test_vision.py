"""Test vision model on a photo that previously got OCR=0."""
import requests, time, base64, json

BASE = "http://localhost:8000/api/v1"
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@local", "password": "mxT-EPCWJKVpfdClt4mJ82puUV7eHw"})
TOKEN = r.json()["access_token"]
HDR = {"Authorization": f"Bearer {TOKEN}"}

# Find a photo document with OCR=0
import subprocess
result = subprocess.run(
    ["docker", "exec", "docu-intel-postgres-1", "psql", "-U", "app", "-d", "docuintel", "-t", "-A", "-c",
     "SELECT d.id, d.original_filename, d.stored_filename FROM document_pages dp JOIN documents d ON d.id = dp.document_id WHERE dp.ocr_confidence = 0 AND d.extension IN ('.jpg','.jpeg','.png') AND d.status != 'duplicate' LIMIT 3;"],
    capture_output=True, encoding="utf-8", timeout=15
)
print("Photos with OCR=0:")
for line in result.stdout.strip().split("\n"):
    if line.strip():
        parts = line.split("|")
        print(f"  id={parts[0]} file={parts[1]} stored={parts[2]}")

# Test vision directly via LM Studio
print("\nTesting vision model directly...")
stored = parts[2].strip() if result.stdout.strip() else None
if stored:
    img_path = f"/app/data/files/{stored}"
    # Read image and encode
    with open(img_path, "rb") as f:
        img_data = base64.b64encode(f.read()).decode()
    
    payload = {
        "model": "qwen3-vl-8b-thinking",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe esta imagen en espanol. Si contiene texto, transcribelo. Si es un mueble o material, describe sus caracteristicas."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_data}"}}
            ]
        }],
        "temperature": 0.0,
        "max_tokens": 500
    }
    
    start = time.time()
    r = requests.post("http://localhost:1234/v1/chat/completions", json=payload, timeout=300)
    elapsed = time.time() - start
    
    if r.status_code == 200:
        data = r.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        if not content.strip():
            content = msg.get("reasoning_content") or ""
        print(f"  Response ({elapsed:.1f}s): {content[:500]}")
    else:
        print(f"  Error: {r.status_code} {r.text[:200]}")
