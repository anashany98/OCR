"""Quick smoke test of the FASE 2 multi-dimensional classifier on the
real BON PLA SOCIEDAD ANONIMA corpus. The script is run via
``docker exec`` so we can use the live database without exposing the
network to the host."""

from __future__ import annotations

from app.database.session import SessionLocal
from app.models.document import Document
from app.models.learning import LearnedPattern
from app.services.classification import LearnedRule
from app.services.classification_v2 import classify_multidim


def main() -> None:
    s = SessionLocal()
    docs = s.query(Document).order_by(Document.id).all()
    rules: list[LearnedRule] = []
    try:
        patterns = s.query(LearnedPattern).filter(LearnedPattern.status == "active").all()
        rules = [
            LearnedRule(
                pattern_value=p.pattern_value,
                target_class=p.target_class,
                confidence=p.confidence,
            )
            for p in patterns
        ]
    except Exception as exc:
        print(f"no learned rules: {exc}")

    print(f"Loaded {len(rules)} learned rules, {len(docs)} documents\n")
    header = (
        f"{'source_format':14s} {'document_type':30s} {'conf':>5s}  "
        f"{'subtype':18s} {'tags':30s} filename"
    )
    print(header)
    print("-" * len(header))
    for doc in docs:
        text = ""
        if doc.pages:
            text = "\n".join(p.text for p in doc.pages if p.text)
        r = classify_multidim(
            filename=doc.original_filename,
            source_path=doc.source_path,
            mime_type=doc.mime_type,
            parser_signature=None,
            text=text[:5000],
            learned_rules=rules,
        )
        tags = ",".join(r.content_tags) if r.content_tags else "-"
        subtype = r.document_subtype or "-"
        print(
            f"{r.source_format:14s} {r.document_type:30s} {r.confidence:5.2f}  "
            f"{subtype:18s} {tags[:30]:30s} {doc.original_filename[:40]}"
        )
    s.close()


if __name__ == "__main__":
    main()
