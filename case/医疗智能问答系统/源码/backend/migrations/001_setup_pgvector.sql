-- Migration: Setup pgvector extension and create indexes
-- Description: Enable pgvector extension and create necessary indexes for vector search
-- Date: 2025-11-12

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create HNSW index for vector similarity search
-- This index uses cosine distance for similarity comparison
-- Note: This should be run after the tables are created by SQLAlchemy
-- Uncomment the following line after initial table creation:
-- CREATE INDEX IF NOT EXISTS idx_document_vectors_embedding ON document_vectors USING hnsw (embedding vector_cosine_ops);

-- Alternative: IVFFlat index (faster build time, but requires training)
-- CREATE INDEX IF NOT EXISTS idx_document_vectors_embedding ON document_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Note: For small datasets (< 1M vectors), you can use a simple index:
-- CREATE INDEX IF NOT EXISTS idx_document_vectors_embedding ON document_vectors USING ivfflat (embedding vector_cosine_ops);
