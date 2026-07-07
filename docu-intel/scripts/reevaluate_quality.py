"""Re-evaluate quality for all needs_review documents with new thresholds."""
from app.database.session import SessionLocal
from app.models import Document, DocumentPage
from app.services.quality import evaluate_document_quality, update_document_quality
from sqlalchemy import select

db = SessionLocal()
docs = list(
    db.scalars(
        select(Document)
        .where(Document.status == "needs_review")
        .where(Document.deleted_at.is_(None))
    ).all()
)
print(f"Documents to re-evaluate: {len(docs)}")

promoted = 0
still_needs = 0
errors = 0

for doc in docs:
    try:
        # Gather text and page count from pages
        pages = list(
            db.scalars(
                select(DocumentPage).where(DocumentPage.document_id == doc.id)
            ).all()
        )
        text = "\n".join((p.text or "") for p in pages)
        page_count = len(pages)
        low_confs = [p.ocr_confidence for p in pages if p.ocr_confidence is not None and p.ocr_confidence < 0.7]

        result = evaluate_document_quality(
            db, doc,
            text=text,
            page_count=page_count,
            low_ocr_confidences=low_confs or None,
        )
        update_document_quality(db, doc, result)
        if result.status == "processed_ok":
            doc.status = "processed"
            promoted += 1
        else:
            still_needs += 1
    except Exception as e:
        print(f"  Error on doc {doc.id}: {type(e).__name__}: {e}")
        errors += 1

db.commit()
db.close()

print(f"\nResults:")
print(f"  Promoted to processed: {promoted}")
print(f"  Still needs_review: {still_needs}")
print(f"  Errors: {errors}")

# Verify
db2 = SessionLocal()
r = db2.execute(
    __import__("sqlalchemy").text(
        "SELECT status, COUNT(*) FROM documents WHERE deleted_at IS NULL GROUP BY status ORDER BY COUNT(*) DESC"
    )
)
print(f"\nFinal document status:")
for row in r:
    print(f"  {row[0]}: {row[1]}")
db2.close()
