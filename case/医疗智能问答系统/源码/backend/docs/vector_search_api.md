# 向量化和搜索 API 文档

## 概述

本文档描述了知识库系统的向量化和搜索 API 接口。这些接口用于文档向量化处理和基于向量相似度的智能搜索。

## 认证

所有接口都需要 Bearer Token 认证：

```
Authorization: Bearer <token>
```

## 接口列表

### 1. 向量化单个文档

向量化指定的文档，生成文本块并存储向量数据。

**端点：** `POST /api/kb/{kb_id}/documents/{doc_id}/vectorize`

**路径参数：**
- `kb_id` (string): 知识库ID
- `doc_id` (string): 文档ID

**请求体：**
```json
{
  "force": false,           // 可选，是否强制重新向量化，默认 false
  "chunkSize": 1000,        // 可选，文本块大小
  "chunkOverlap": 200       // 可选，文本块重叠大小
}
```

**响应示例（成功）：**
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "message": "文档向量化成功，生成 5 个文本块",
    "document": {
      "id": "20251112091452794",
      "title": "人工智能简介",
      "vectorStatus": "completed",
      "chunkCount": 5,
      ...
    }
  }
}
```

**响应示例（已向量化，跳过）：**
```json
{
  "success": true,
  "data": {
    "message": "文档已经向量化，如需重新向量化请设置 force=true",
    "document": {...}
  }
}
```

**错误响应：**
- `404`: 知识库或文档不存在
- `400`: 文档未发布或内容为空
- `500`: 向量化处理失败

**使用说明：**
- 只能向量化状态为 `published` 的文档
- 如果文档已经向量化且 `force=false`，将跳过处理
- 设置 `force=true` 可以强制重新向量化
- 向量化过程会自动分割文本并生成嵌入向量

---

### 2. 批量同步知识库向量

批量同步知识库中所有已发布文档的向量数据。

**端点：** `POST /api/kb/{kb_id}/sync-vectors`

**路径参数：**
- `kb_id` (string): 知识库ID

**请求体：**
```json
{
  "force": false,                    // 可选，是否强制重新同步所有文档
  "documentIds": [],                 // 可选，指定要同步的文档ID列表
  "chunkSize": 1000,                 // 可选，文本块大小
  "chunkOverlap": 200                // 可选，文本块重叠大小
}
```

**响应示例：**
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "message": "向量同步完成：成功 8 个，失败 1 个",
    "summary": {
      "total": 9,
      "success": 8,
      "failed": 1,
      "skipped": 0
    },
    "errors": [
      {
        "documentId": "doc123",
        "title": "测试文档",
        "error": "文档内容为空"
      }
    ]
  }
}
```

**错误响应：**
- `404`: 知识库不存在
- `400`: 参数格式错误
- `500`: 同步处理失败

**使用说明：**
- 默认只同步未完成向量化的文档（`vector_status` 为 `pending` 或 `failed`）
- 设置 `force=true` 可以强制重新同步所有文档
- 可以通过 `documentIds` 参数指定要同步的文档列表
- 只处理状态为 `published` 的文档
- 返回详细的成功/失败统计信息

---

### 3. 知识库内搜索

在指定知识库内搜索文档。

**端点：** `POST /api/kb/{kb_id}/search`

**路径参数：**
- `kb_id` (string): 知识库ID

**请求体：**
```json
{
  "query": "人工智能",              // 必需，搜索关键词
  "limit": 10,                      // 可选，返回结果数量，默认 10
  "searchType": "hybrid",           // 可选，搜索类型：vector, sql, hybrid，默认 hybrid
  "similarityThreshold": 0.7,       // 可选，向量搜索相似度阈值，默认 0.7
  "highlight": true                 // 可选，是否高亮显示，默认 true
}
```

**响应示例：**
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "results": [
      {
        "document": {
          "id": "doc123",
          "title": "人工智能简介",
          "content": "...",
          "category": "技术",
          ...
        },
        "similarity": 0.92,
        "searchType": "vector",
        "matchedContent": "人工智能（Artificial Intelligence，AI）是计算机科学的一个分支...",
        "highlightedContent": "<mark>人工智能</mark>（Artificial Intelligence，AI）是计算机科学的一个分支...",
        "matchedChunks": 3
      }
    ],
    "query": "人工智能",
    "total": 5,
    "searchType": "hybrid"
  }
}
```

**错误响应：**
- `404`: 知识库不存在
- `400`: 缺少必需参数或参数格式错误
- `500`: 搜索处理失败

**搜索类型说明：**
- `vector`: 纯向量相似度搜索，基于语义理解
- `sql`: 纯 SQL 全文搜索，基于关键词匹配
- `hybrid`: 混合搜索（推荐），先进行向量搜索，结果不足时补充 SQL 搜索

**使用说明：**
- 只搜索状态为 `published` 的文档
- 向量搜索基于语义相似度，可以找到语义相关的内容
- SQL 搜索基于关键词匹配，适合精确查找
- 混合搜索结合两种方式的优点，提供最佳搜索体验
- 高亮功能会在匹配内容中用 `<mark>` 标签标记关键词

---

### 4. 跨知识库搜索

在所有知识库或指定的多个知识库中搜索文档。

**端点：** `POST /api/kb/search`

**请求体：**
```json
{
  "query": "机器学习",              // 必需，搜索关键词
  "limit": 10,                      // 可选，返回结果数量，默认 10
  "searchType": "hybrid",           // 可选，搜索类型：vector, sql, hybrid，默认 hybrid
  "similarityThreshold": 0.7,       // 可选，向量搜索相似度阈值，默认 0.7
  "highlight": true,                // 可选，是否高亮显示，默认 true
  "kbIds": []                       // 可选，限制搜索的知识库ID列表，为空则搜索所有
}
```

**响应示例：**
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "results": [
      {
        "document": {
          "id": "doc123",
          "title": "机器学习基础",
          "content": "...",
          ...
        },
        "knowledgeBase": {
          "id": "kb001",
          "name": "AI技术知识库",
          "description": "人工智能相关技术文档"
        },
        "similarity": 0.95,
        "searchType": "vector",
        "matchedContent": "机器学习是人工智能的一个分支...",
        "highlightedContent": "<mark>机器学习</mark>是人工智能的一个分支...",
        "matchedChunks": 2
      }
    ],
    "query": "机器学习",
    "total": 8,
    "searchType": "hybrid"
  }
}
```

**错误响应：**
- `400`: 缺少必需参数或参数格式错误
- `404`: 指定的知识库不存在
- `500`: 搜索处理失败

**使用说明：**
- 不指定 `kbIds` 时搜索所有知识库
- 指定 `kbIds` 可以限制搜索范围到特定的知识库
- 结果按相似度排序，包含文档和所属知识库的信息
- 其他功能与知识库内搜索相同

---

## 向量化状态说明

文档的 `vectorStatus` 字段表示向量化状态：

- `pending`: 待向量化
- `processing`: 向量化处理中
- `completed`: 向量化完成
- `failed`: 向量化失败

## 最佳实践

### 1. 文档向量化

```javascript
// 创建文档后立即向量化
const doc = await createDocument(kbId, {
  title: "新文档",
  content: "文档内容...",
  status: "published"
});

// 向量化文档
await vectorizeDocument(kbId, doc.id);
```

### 2. 批量同步

```javascript
// 定期同步知识库向量（处理失败的文档）
await syncVectors(kbId, {
  force: false  // 只同步未完成的文档
});

// 内容更新后强制重新同步
await syncVectors(kbId, {
  force: true,
  documentIds: [doc1.id, doc2.id]  // 只同步指定文档
});
```

### 3. 智能搜索

```javascript
// 使用混合搜索获得最佳结果
const results = await searchInKb(kbId, {
  query: "用户查询",
  searchType: "hybrid",
  limit: 10,
  highlight: true
});

// 跨知识库搜索
const globalResults = await searchAllKbs({
  query: "全局查询",
  kbIds: [kb1.id, kb2.id],  // 限制搜索范围
  searchType: "hybrid"
});
```

## 性能优化建议

1. **批量处理**：使用批量同步接口而不是逐个向量化文档
2. **增量更新**：默认使用 `force=false`，只处理需要更新的文档
3. **合理的块大小**：根据文档类型调整 `chunkSize` 和 `chunkOverlap`
4. **搜索类型选择**：
   - 语义搜索使用 `vector`
   - 精确匹配使用 `sql`
   - 一般情况使用 `hybrid`
5. **相似度阈值**：根据实际需求调整 `similarityThreshold`，过低会返回不相关结果

## 错误处理

所有接口都遵循统一的错误响应格式：

```json
{
  "success": false,
  "message": "错误描述",
  "error_code": null
}
```

常见错误及处理：

1. **向量化失败**：检查文档内容是否为空，嵌入模型是否可用
2. **搜索无结果**：尝试降低相似度阈值或使用 SQL 搜索
3. **连接错误**：检查 PostgreSQL 和嵌入 API 服务是否正常运行

## 相关配置

环境变量配置：

```bash
# 嵌入模型 API
EMBEDDINGS_API_URL=http://localhost:11434/api/embeddings
EMBEDDING_MODEL=nomic-embed-text

# PostgreSQL 向量数据库
VECTOR_DATABASE_URL=postgresql://user:pass@localhost:5432/vectors

# 默认参数
DEFAULT_CHUNK_SIZE=1000
DEFAULT_CHUNK_OVERLAP=200
DEFAULT_SIMILARITY_THRESHOLD=0.7
```
