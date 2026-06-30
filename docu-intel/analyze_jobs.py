from app.database.session import SessionLocal
from app.models import Document, ExtractionJob, DocumentPage
from sqlalchemy import func

db = SessionLocal()

# Failed jobs
failed_jobs = db.query(ExtractionJob).filter(ExtractionJob.status == 'failed').all()
print("=== FAILED JOBS:", len(failed_jobs), "===")
errors = {}
for job in failed_jobs[:30]:
    doc = db.query(Document).get(job.document_id)
    fname = doc.original_filename if doc else "?"
    err = (job.error_message or "?")[:150]
    print("  Job", job.id, ":", fname)
    print("    Error:", err)
    # Count error types
    err_type = err.split(":")[0][:60] if err else "unknown"
    errors[err_type] = errors.get(err_type, 0) + 1

print()
print("=== ERROR SUMMARY ===")
for err, count in sorted(errors.items(), key=lambda x: -x[1]):
    print(f"  {count}x: {err}")

print()

# Documents by status
statuses = db.query(Document.status, func.count(Document.id)).group_by(Document.status).all()
print("=== DOCUMENTS BY STATUS ===")
for s, c in statuses:
    print(f"  {s}: {c}")

print()

# Documents needing review
review = db.query(Document).filter(Document.status == 'needs_review').limit(15).all()
print("=== NEEDS REVIEW:", len(review), "===")
for d in review:
    pages = db.query(DocumentPage).filter(DocumentPage.document_id == d.id).all()
    avg_conf = sum(p.ocr_confidence or 0 for p in pages) / max(len(pages), 1)
    print(f"  {d.original_filename} | conf={avg_conf:.2f} | pages={len(pages)} | type={d.document_type}")

print()

# Low confidence docs
low_conf = db.query(DocumentPage).filter(
    DocumentPage.ocr_confidence < 0.5,
    DocumentPage.ocr_confidence.is_not(None)
).count()
print("=== PAGES WITH LOW CONFIDENCE (<0.5):", low_conf, "===")

# Failed documents
failed_docs = db.query(Document).filter(Document.status == 'failed').limit(10).all()
print()
print("=== FAILED DOCUMENTS:", len(failed_docs), "===")
for d in failed_docs:
    print(f"  {d.original_filename} | type={d.document_type} | error={(d.error_message or '?')[:100]}")

db.close()
