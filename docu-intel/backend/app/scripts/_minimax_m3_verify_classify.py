"""Verify FASE 2 classification persistence on the real corpus."""
from app.database.session import SessionLocal
from app.models.document import Document


def main() -> None:
    s = SessionLocal()
    docs = s.query(Document).order_by(Document.id).all()
    header = (
        f"{'id':>7s} {'source_format':14s} {'document_type':18s} "
        f"{'subtype':15s} {'tags':25s} {'conf':>5s} "
        f"{'classifier':25s} {'classified_at':>10s}"
    )
    print(header)
    print("-" * len(header))
    for d in docs:
        tags = ",".join(d.content_tags) if d.content_tags else "-"
        sub = d.document_subtype or "-"
        cat = d.classified_at.strftime("%H:%M:%S") if d.classified_at else "-"
        classifier = d.classifier_version or "-"
        conf = f"{d.confidence:.2f}" if d.confidence is not None else "-"
        print(
            f"{d.id:7d} {(d.source_format or '-'):14s} "
            f"{d.document_type:18s} {sub:15s} {tags[:25]:25s} "
            f"{conf:>5s} {classifier:25s} {cat:>10s}"
        )
    s.close()


if __name__ == "__main__":
    main()
