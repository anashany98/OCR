"""One-shot row counts for the ingestion monitor cron."""
from app.database.session import get_engine
from sqlalchemy import text

e = get_engine()
c = e.connect()
docs = c.execute(text("SELECT count(*) FROM documents WHERE deleted_at IS NULL")).scalar()
chunks = c.execute(text("SELECT count(*) FROM document_chunks")).scalar()
rels = c.execute(text("SELECT count(*) FROM graph_relations")).scalar()
errs = c.execute(text("SELECT count(*) FROM graph_extraction_errors")).scalar()
processed = c.execute(text("SELECT count(*) FROM documents WHERE deleted_at IS NULL AND status='processed'")).scalar()
print(f"{docs}/{chunks} docs, {processed} processed, {rels} rels, {errs} errors")
