-- Migration: Create additional indexes for performance
-- Description: Create indexes on frequently queried columns
-- Date: 2025-11-12

-- Knowledge Base indexes
CREATE INDEX IF NOT EXISTS idx_knowledge_bases_status ON knowledge_bases(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_bases_created_at ON knowledge_bases(created_at DESC);

-- Document indexes
CREATE INDEX IF NOT EXISTS idx_documents_kb_status ON documents(kb_id, status);
CREATE INDEX IF NOT EXISTS idx_documents_vector_status ON documents(kb_id, vector_status);
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category);

-- Document Vector indexes (already defined in model, but listed here for reference)
-- CREATE INDEX IF NOT EXISTS idx_document_vectors_kb_id ON document_vectors(kb_id);
-- CREATE INDEX IF NOT EXISTS idx_document_vectors_document_id ON document_vectors(document_id);
-- CREATE INDEX IF NOT EXISTS idx_document_vectors_kb_doc ON document_vectors(kb_id, document_id);
-- CREATE INDEX IF NOT EXISTS idx_document_vectors_chunk ON document_vectors(document_id, chunk_index);

-- Full-text search index for documents (PostgreSQL specific)
-- This enables hybrid search combining vector similarity and keyword matching
CREATE INDEX IF NOT EXISTS idx_documents_content_fts ON documents USING gin(to_tsvector('english', content));
CREATE INDEX IF NOT EXISTS idx_documents_title_fts ON documents USING gin(to_tsvector('english', title));
