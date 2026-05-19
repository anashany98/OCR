-- =============================================================================
-- pgvector Index Optimization Script
-- =============================================================================
-- Run this script to create HNSW indexes for fast vector similarity search.
-- Based on pgvector best practices 2026.
--
-- Usage:
--   docker exec -i <postgres_container> psql -U app -d docuintel < optimize_vector_indexes.sql
--
-- Or connect to PostgreSQL and run manually:
--   docker exec -it <postgres_container> psql -U app -d docuintel
--   \i /path/to/optimize_vector_indexes.sql
-- =============================================================================

-- Ensure pgvector extension is installed
CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- HNSW Indexes for Fast Approximate Nearest Neighbor Search
-- =============================================================================

-- Index for document_chunks.embedding (primary vector column)
-- Parameters:
--   m = 16: Number of bi-directional links for each node (balance between speed and recall)
--   ef_construction = 64: Size of dynamic candidate list during index build
-- These values are optimal for tables with < 100K rows

CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw 
ON document_chunks 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Index for documents.embedding (if exists)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'documents' AND column_name = 'embedding'
    ) THEN
        CREATE INDEX IF NOT EXISTS ix_documents_embedding_hnsw 
        ON documents 
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
    END IF;
END $$;

-- =============================================================================
-- Supporting B-tree Indexes for Hybrid Search
-- =============================================================================

-- Index for document_id lookups (common in filtered searches)
CREATE INDEX IF NOT EXISTS ix_document_chunks_document_id 
ON document_chunks(document_id);

-- Index for presupuesto_id filtering
CREATE INDEX IF NOT EXISTS ix_document_chunks_presupuesto_id 
ON document_chunks(presupuesto_id);

-- Composite index for document_type + created_at (filtered time-series queries)
CREATE INDEX IF NOT EXISTS ix_document_chunks_doc_type_created 
ON document_chunks(document_type, created_at DESC);

-- Index for budget_scope_id filtering (multi-tenant isolation)
CREATE INDEX IF NOT EXISTS ix_document_chunks_budget_scope_id 
ON document_chunks(budget_scope_id);

-- =============================================================================
-- PostgreSQL Configuration
-- =============================================================================

-- Set default HNSW search parameters
-- Higher ef_search = better recall but slower queries
-- Recommended range: 20-100 (40 is a good balance)
ALTER DATABASE docuintel SET hnsw.ef_search = 40;

-- Ensure shared_preload_libraries includes pgvector (requires restart)
-- Note: This is typically set in postgresql.conf
-- SHOW shared_preload_libraries;

-- =============================================================================
-- Statistics and Maintenance
-- =============================================================================

-- Analyze tables to update statistics
ANALYZE document_chunks;
ANALYZE documents;

-- Check table and index sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as total_size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) as table_size,
    pg_size_pretty(pg_indexes_size(schemaname||'.'||tablename)) as indexes_size
FROM pg_tables 
WHERE tablename IN ('document_chunks', 'documents')
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Verify indexes are being used (run EXPLAIN ANALYZE on a sample query)
-- EXPLAIN ANALYZE
-- SELECT id, embedding <=> '[0.1, 0.2, ...]'::vector AS distance
-- FROM document_chunks
-- ORDER BY distance
-- LIMIT 10;

-- =============================================================================
-- Performance Recommendations
-- =============================================================================
-- 
-- 1. VACUUM after large inserts:
--    VACUUM ANALYZE document_chunks;
--
-- 2. For tables > 100K rows, consider increasing HNSW parameters:
--    m = 24, ef_construction = 96
--
-- 3. Monitor index build memory:
--    SET maintenance_work_mem = '2GB';  -- For large index builds
--
-- 4. For datasets > 500K vectors, consider migrating to Qdrant
--    See: https://qdrant.tech/blog/pgvector-tradeoffs/
--
-- =============================================================================
