# Weaviate to pgvector Migration - Cleanup Summary

## Overview
This document summarizes the cleanup of old Weaviate-related code after migrating to pgvector.

## Files Deleted

### Backend
1. **backend/utils/vector_db.py** - Old Weaviate-based vector database manager
   - Contained VectorDBManager class with Weaviate client integration
   - Handled article vectorization using Weaviate
   - Replaced by: `backend/utils/vector_manager.py` (pgvector-based)

2. **backend/routes/knowledge.py** - Legacy knowledge base routes
   - Old API endpoints using Weaviate
   - Endpoints: `/api/knowledge/*`
   - Replaced by: `backend/routes/kb.py` (pgvector-based)

3. **backend/manual_create_collection.py** - Manual Weaviate collection creation script
   - Script for manually creating Weaviate collections
   - No longer needed with pgvector

## Files Modified

### Backend

1. **backend/app/__init__.py**
   - Removed import of `knowledge_bp` from routes.knowledge
   - Removed registration of knowledge_bp blueprint
   - Now only uses the new `kb_bp` blueprint

2. **backend/models/knowledge_article.py**
   - Updated comment for `vector_id` field to indicate it's legacy
   - Field kept for backward compatibility but no longer used

### Frontend

1. **frotend/src/pages/KnowledgeBase.tsx**
   - Changed `VectorDbType` from multiple options to only 'pgvector'
   - Updated default vector database type from 'Weaviate' to 'pgvector'
   - Disabled vector database type dropdown (now read-only)
   - Added explanatory text: "系统现在使用 pgvector 作为向量数据库"
   - Updated all default settings to use 'pgvector'

## Import Changes

### Removed Imports
- `from utils.vector_db import get_vector_db_manager` (in routes/knowledge.py)
- `from utils.vector_db import VectorDBManager` (in routes/knowledge.py)
- `from routes.knowledge import knowledge_bp` (in app/__init__.py)

### No New Dependencies Required
- All pgvector functionality uses existing dependencies:
  - psycopg2-binary (already in requirements.txt)
  - pgvector (already in requirements.txt)
  - langchain libraries (already in requirements.txt)

## API Changes

### Removed Endpoints
All `/api/knowledge/*` endpoints have been removed:
- GET /api/knowledge/articles
- POST /api/knowledge/articles
- GET /api/knowledge/articles/{id}
- PUT /api/knowledge/articles/{id}
- DELETE /api/knowledge/articles/{id}
- POST /api/knowledge/articles/batch
- GET /api/knowledge/categories
- POST /api/knowledge/search
- GET /api/knowledge/stats
- GET /api/knowledge/settings
- PUT /api/knowledge/settings
- POST /api/knowledge/test-connection
- POST /api/knowledge/create-collection
- POST /api/knowledge/sync-vectors

### Replacement Endpoints
All functionality now available through `/api/kb/*` endpoints (see backend/docs/kb_api_implementation.md)

## Configuration Changes

### Environment Variables
No Weaviate-specific environment variables are needed anymore:
- ~~WEAVIATE_URL~~ (removed)
- ~~WEAVIATE_API_KEY~~ (removed)

PostgreSQL connection is now used via existing `DATABASE_URL`.

### Frontend Configuration
- Vector database type is now hardcoded to 'pgvector'
- Users can no longer select different vector database types
- Connection string now refers to PostgreSQL database (not Weaviate URL)

## Testing Impact

### Tests to Update/Remove
- Any tests that imported from `utils.vector_db` need to be updated
- Tests for `/api/knowledge/*` endpoints should be removed or updated to use `/api/kb/*`

### New Tests
- Tests for pgvector functionality are in:
  - backend/test_vector_manager.py
  - backend/test_vector_search.py

## Migration Notes

### Data Migration
- No data migration needed as this is a new implementation
- Old Weaviate data (if any) is not migrated
- Users need to re-vectorize documents using the new system

### Backward Compatibility
- The `vector_id` field in `knowledge_articles` table is kept but unused
- The `chunk_count` field is still used by the new system
- Old API endpoints are completely removed (no backward compatibility)

## Verification Steps

1. ✅ Backend starts without import errors
2. ✅ No references to Weaviate in active code
3. ✅ Frontend compiles without errors
4. ✅ New pgvector-based endpoints work correctly
5. ✅ No unused dependencies in requirements.txt

## Future Cleanup (Optional)

### Database Schema
Consider removing the `vector_id` column from `knowledge_articles` table in a future migration:
```sql
ALTER TABLE knowledge_articles DROP COLUMN vector_id;
```

### Legacy Models
The `KnowledgeArticle` model could be deprecated in favor of the new `Document` model once all features are migrated.

## References

- New pgvector implementation: `backend/utils/vector_manager.py`
- New API routes: `backend/routes/kb.py`
- Database schema: `backend/docs/database_schema.md`
- Vector search documentation: `backend/docs/vector_search_api.md`
