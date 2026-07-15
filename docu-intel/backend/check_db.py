"""Quick DB health check after migration."""
from sqlalchemy import create_engine, text

e = create_engine('postgresql+psycopg://app:51ExkzaApki70FA-x25XqIDoMUAo4Q@postgres:5432/docuintel')
with e.connect() as c:
    # Documents
    r = c.execute(text('SELECT count(*) FROM documents WHERE deleted_at IS NULL'))
    print(f'Documents: {r.scalar()}')

    # Chunks
    r = c.execute(text('SELECT count(*) FROM document_chunks'))
    print(f'Chunks: {r.scalar()}')

    # Embeddings
    r = c.execute(text('SELECT count(*) FROM document_chunks WHERE embedding IS NOT NULL'))
    print(f'With embeddings: {r.scalar()}')

    r = c.execute(text('SELECT count(*) FROM document_chunks WHERE needs_reembedding = true'))
    print(f'Need re-embed: {r.scalar()}')

    # Block types
    r = c.execute(text('SELECT block_type, count(*) FROM document_blocks GROUP BY block_type ORDER BY count DESC'))
    print('Block types:')
    for row in r:
        print(f'  {row[0]}: {row[1]}')

    # Financial columns
    r = c.execute(text("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_name IN ('invoices', 'budgets', 'orders', 'order_lines', 'budget_lines')
        AND column_name IN ('total_amount', 'unit_price', 'total_price', 'taxable_base', 'vat_amount')
        ORDER BY table_name, column_name
    """))
    print('Financial columns:')
    for row in r:
        print(f'  {row[0]}.{row[1]}: {row[2]}')

    # Embedding versions
    r = c.execute(text("""
        SELECT embedding_model_version, count(*)
        FROM document_chunks
        WHERE embedding IS NOT NULL
        GROUP BY embedding_model_version
    """))
    print('Embedding versions:')
    for row in r:
        print(f'  {row[0]}: {row[1]}')

    # Check constraint
    r = c.execute(text("""
        SELECT conname, pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conname = 'ck_document_blocks_block_type'
    """))
    row = r.fetchone()
    if row:
        print(f'Block type constraint: {row[0]}')
        print(f'  Definition: {row[1][:100]}...')

    # Migration version
    r = c.execute(text('SELECT version_num FROM alembic_version'))
    print(f'Migration version: {r.scalar()}')
