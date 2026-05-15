"""
Database Query Analyzer
Helps identify N+1 queries and slow queries.

Run with: python -m tests.performance.db_query_analyzer
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import event, create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://app:app@localhost:5432/docuintel")


class QueryStats:
    def __init__(self):
        self.queries = []
        self.query_counts = {}

    def record(self, conn, cursor, statement, parameters, context, executemany):
        query_key = statement.strip()[:100]
        self.query_counts[query_key] = self.query_counts.get(query_key, 0) + 1
        self.queries.append({"sql": statement, "params": str(parameters)[:200]})


stats = QueryStats()


def setup_query_monitoring(engine):
    event.listen(engine, "before_cursor_execute", stats.record)


def analyze_queries():
    print("\n" + "=" * 60)
    print("QUERY ANALYSIS")
    print("=" * 60)

    if not stats.query_counts:
        print("No queries recorded. Make requests first.")
        return

    print(f"\nTotal unique query patterns: {len(stats.query_counts)}")
    print(f"Total queries executed: {sum(stats.query_counts.values())}")

    print("\nQuery frequency (top 20):")
    sorted_queries = sorted(stats.query_counts.items(), key=lambda x: x[1], reverse=True)
    for i, (query, count) in enumerate(sorted_queries[:20]):
        print(f"  {i + 1}. [{count:4d}x] {query[:80]}...")

    high_frequency = [(q, c) for q, c in sorted_queries if c > 10]
    if high_frequency:
        print("\n⚠️  HIGH FREQUENCY QUERIES (potential N+1):")
        for query, count in high_frequency[:10]:
            print(f"     {count}x: {query[:60]}...")


def get_slow_queries_postgres(connection):
    print("\n" + "=" * 60)
    print("SLOW QUERIES (from pg_stat_statements)")
    print("=" * 60)

    try:
        result = connection.execute(text("""
            SELECT query, calls, total_time, mean_time, max_time
            FROM pg_stat_statements
            WHERE mean_time > 100
            ORDER BY mean_time DESC
            LIMIT 20
        """))
        rows = result.fetchall()

        if not rows:
            print("No slow queries found (threshold: mean_time > 100ms)")
            return

        print(f"\n{'Query':<60} {'Calls':>8} {'Avg ms':>10} {'Max ms':>10}")
        print("-" * 90)
        for row in rows:
            query = row[0][:60] if row[0] else ""
            print(f"{query:<60} {row[1]:>8} {row[3]:>10.2f} {row[4]:>10.2f}")
    except Exception as e:
        print(f"pg_stat_statements not available: {e}")
        print("Enable with: CREATE EXTENSION IF NOT EXISTS pg_stat_statements;")


def check_indexes(connection, table_name):
    print("\n" + "=" * 60)
    print(f"INDEX CHECK for {table_name}")
    print("=" * 60)

    result = connection.execute(text("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = :table
        ORDER BY indexname
    """), {"table": table_name})

    indexes = result.fetchall()
    print(f"\nIndexes on {table_name}:")
    for idx in indexes:
        print(f"  {idx[0]}: {idx[1]}")

    if not indexes:
        print("  ⚠️  NO INDEXES FOUND!")


def analyze_n_plus_one():
    print("\n" + "=" * 60)
    print("N+1 DETECTION")
    print("=" * 60)

    patterns = stats.query_counts
    n_plus_one = []

    for query, count in patterns.items():
        query_lower = query.lower()
        if "select" in query_lower and "where" in query_lower and "id =" in query_lower:
            if count > 20:
                n_plus_one.append((query, count))

    if n_plus_one:
        print("\n⚠️  Potential N+1 detected:")
        for query, count in n_plus_one[:10]:
            print(f"     {count}x: {query[:70]}...")
    else:
        print("\n✓ No obvious N+1 patterns detected")


if __name__ == "__main__":
    setup_query_monitoring(create_engine(DATABASE_URL))

    with create_engine(DATABASE_URL).connect() as conn:
        get_slow_queries_postgres(conn)

        for table in ["documents", "document_pages", "document_chunks", "budgets", "orders"]:
            check_indexes(conn, table)

    analyze_n_plus_one()
    analyze_queries()
