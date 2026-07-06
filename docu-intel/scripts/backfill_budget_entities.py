"""Backfill budget_number entities from source_path for all documents."""
import re
from pathlib import PurePosixPath
from app.database.session import SessionLocal
from app.models import Document, DocumentEntity
from sqlalchemy import select


def extract_budget_code(path):
    if not path:
        return None
    normalized = path.replace("\\", "/").strip()
    parts = [p for p in PurePosixPath(normalized).parts if p not in {"/", ""}]
    for part in reversed(parts):
        m = re.match(r"(?i)^presupuesto\s+(\S+)", part)
        if m:
            return m.group(1).strip()
    return None


db = SessionLocal()
docs = db.scalars(
    select(Document).where(Document.source_path.isnot(None)).where(Document.deleted_at.is_(None))
).all()

created = 0
updated = 0
skipped = 0

for doc in docs:
    code = extract_budget_code(doc.source_path)
    if not code:
        skipped += 1
        continue

    existing = db.scalar(
        select(DocumentEntity).where(
            DocumentEntity.document_id == doc.id,
            DocumentEntity.entity_type == "budget_number",
        )
    )
    if existing:
        if existing.entity_value != code:
            existing.entity_value = code
            existing.normalized_value = code.lower().strip()
            updated += 1
    else:
        db.add(
            DocumentEntity(
                document_id=doc.id,
                entity_type="budget_number",
                entity_value=code,
                normalized_value=code.lower().strip(),
                confidence=0.9,
            )
        )
        created += 1

db.commit()
print(f"Created: {created}, Updated: {updated}, Skipped (no code): {skipped}")
print(f"Total docs processed: {len(docs)}")

# Verify
count = db.scalar(select(DocumentEntity).where(DocumentEntity.entity_type == "budget_number"))
print(f"Total budget_number entities now: {count}")
db.close()
