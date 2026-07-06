"""Test vision model on photo from inside container."""
import base64, time, json
from pathlib import Path
from app.ai.local_client import LocalVisionClient
from app.services.vision_manager import VisionManager

# Find a photo with OCR=0
from app.database.session import SessionLocal
from sqlalchemy import text
db = SessionLocal()
row = db.execute(text(
    "SELECT d.stored_filename FROM document_pages dp "
    "JOIN documents d ON d.id = dp.document_id "
    "WHERE dp.ocr_confidence = 0 AND d.extension IN ('.jpg','.jpeg') "
    "AND d.status != 'duplicate' LIMIT 1"
)).fetchone()

if not row:
    print("No photos with OCR=0 found")
    exit(1)

stored = row[0]
img_path = Path(f"/app/data/files/{stored}")
print(f"Testing with: {img_path} (exists={img_path.exists()})")

# Test the vision client
VisionManager.cancel_pending_unload()
if not VisionManager.is_loaded():
    print("Loading vision model...")
    VisionManager.ensure_loaded()

client = LocalVisionClient()
prompt = (
    "Describe esta imagen en espanol con detalle. "
    "Si contiene texto, transcribelo literalmente. "
    "Si es un mueble, material o producto, describe sus caracteristicas "
    "(tipo, color, dimensiones, material, estado)."
)

start = time.time()
try:
    result = client.describe.__wrapped__ if hasattr(client.describe, '__wrapped__') else client.describe
    import asyncio
    result = asyncio.run(client.describe(img_path, prompt=prompt, max_tokens=500))
    elapsed = time.time() - start
    print(f"\nResponse ({elapsed:.1f}s):")
    print(result[:800] if result else "EMPTY")
except Exception as e:
    elapsed = time.time() - start
    print(f"\nError ({elapsed:.1f}s): {type(e).__name__}: {e}")

VisionManager.schedule_unload()
db.close()
