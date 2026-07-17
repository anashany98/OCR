"""Cron-friendly row counts for the Graph RAG watch."""
from app.database.session import get_engine
from sqlalchemy import text

e = get_engine()
c = e.connect()
print("docs", c.execute(text("SELECT count(*) FROM documents WHERE deleted_at IS NULL")).scalar())
print("chunks", c.execute(text("SELECT count(*) FROM document_chunks")).scalar())
print("ents", c.execute(text("SELECT count(*) FROM document_entities")).scalar())
print("graph_e", c.execute(text("SELECT count(*) FROM graph_entities")).scalar())
print("graph_r", c.execute(text("SELECT count(*) FROM graph_relations")).scalar())
