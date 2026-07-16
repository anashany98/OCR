"""Check re-embedding sweep status."""
from sqlalchemy import create_engine, text

e = create_engine('postgresql+psycopg://app:51ExkzaApki70FA-x25XqIDoMUAo4Q@postgres:5432/docuintel')
with e.connect() as c:
    # Chunks needing re-embed
    r = c.execute(text('SELECT count(*) FROM document_chunks WHERE needs_reembedding = true'))
    print(f'Chunks needing re-embed: {r.scalar()}')

    # Recent extraction jobs
    r = c.execute(text("""
        SELECT job_type, status, count(*)
        FROM extraction_jobs
        WHERE created_at > now() - interval '1 hour'
        GROUP BY job_type, status
    """))
    print('Recent jobs (last hour):')
    for row in r:
        print(f'  {row[0]} ({row[1]}): {row[2]}')

    # Recent embedding-related audit logs
    r = c.execute(text("""
        SELECT created_at, action, details_json
        FROM audit_logs
        WHERE action LIKE '%embed%'
        ORDER BY created_at DESC
        LIMIT 5
    """))
    print('Recent embedding audit logs:')
    for row in r:
        print(f'  {row[0]}: {row[1]} - {row[2]}')

    # Check if Celery beat is running (look for periodic task entries)
    r = c.execute(text("""
        SELECT task_name, last_run_at, total_run_count
        FROM celery_periodic_task
        WHERE task_name LIKE '%reembed%'
    """))
    print('Re-embed periodic tasks:')
    for row in r:
        print(f'  {row[0]}: last_run={row[1]}, runs={row[2]}')
