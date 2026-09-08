# 设置管理 API 实现文档

## 概述

本文档描述了知识库设置管理 API 的实现，包括获取设置、更新设置和测试嵌入模型连接的功能。

## 实现的功能

### 1. 获取知识库设置 (GET /api/settings/knowledge-base)

**功能描述：**
- 获取当前的知识库设置
- 如果设置不存在，自动创建默认设置

**请求示例：**
```bash
curl -X GET http://localhost:5000/api/settings/knowledge-base \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**响应示例：**
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "settings": {
      "id": "default",
      "vectorDbType": "pgvector",
      "connectionString": null,
      "embeddingModel": "nomic-embed-text",
      "embeddingDimension": 1536,
      "chunkSize": 1000,
      "chunkOverlap": 200,
      "similarityThreshold": 0.7,
      "maxSearchResults": 10,
      "createdAt": "2025-11-12T09:23:33.635317",
      "updatedAt": "2025-11-12T09:23:33.635317"
    }
  }
}
```

### 2. 更新知识库设置 (PUT /api/settings/knowledge-base)

**功能描述：**
- 更新知识库设置
- 支持部分更新（只更新提供的字段）
- 包含参数验证

**请求示例：**
```bash
curl -X PUT http://localhost:5000/api/settings/knowledge-base \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "embeddingModel": "text-embedding-3-small",
    "embeddingDimension": 768,
    "chunkSize": 1500,
    "chunkOverlap": 300,
    "similarityThreshold": 0.8,
    "maxSearchResults": 20
  }'
```

**响应示例：**
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "message": "设置更新成功",
    "settings": {
      "id": "default",
      "vectorDbType": "pgvector",
      "connectionString": null,
      "embeddingModel": "text-embedding-3-small",
      "embeddingDimension": 768,
      "chunkSize": 1500,
      "chunkOverlap": 300,
      "similarityThreshold": 0.8,
      "maxSearchResults": 20,
      "createdAt": "2025-11-12T09:23:33.635317",
      "updatedAt": "2025-11-12T09:23:33.647253"
    }
  }
}
```

**参数验证规则：**
- `embeddingDimension`: 必须是正整数
- `chunkSize`: 必须是正整数
- `chunkOverlap`: 必须是非负整数
- `similarityThreshold`: 必须在 0 到 1 之间
- `maxSearchResults`: 必须是正整数

**错误响应示例：**
```json
{
  "success": false,
  "message": "文本块大小必须是正整数",
  "error_code": null
}
```

### 3. 测试嵌入模型连接 (POST /api/settings/test-embedding)

**功能描述：**
- 测试嵌入模型 API 的连接和可用性
- 支持 OpenAI 和 Ollama 两种 API 风格
- 返回模型维度和 API 风格信息

**请求示例：**
```bash
curl -X POST http://localhost:5000/api/settings/test-embedding \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "embeddingModel": "nomic-embed-text",
    "embeddingApiUrl": "http://127.0.0.1:11434/api/embeddings",
    "testText": "这是一个测试文本"
  }'
```

**成功响应示例（模型可用）：**
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "message": "嵌入模型连接成功",
    "available": true,
    "model": "nomic-embed-text",
    "apiUrl": "http://127.0.0.1:11434/api/embeddings",
    "dimension": 768,
    "apiStyle": "Ollama",
    "testText": "这是一个测试文本"
  }
}
```

**失败响应示例（模型不可用）：**
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "message": "嵌入模型不可用",
    "available": false,
    "model": "nomic-embed-text",
    "apiUrl": "http://127.0.0.1:11434/api/embeddings",
    "error": "无法连接到 API，请检查服务是否运行"
  }
}
```

## 技术实现细节

### 文件结构

```
backend/
├── routes/
│   └── settings.py          # 设置管理路由
├── models/
│   └── settings.py          # 设置模型（已存在）
├── app/
│   └── __init__.py          # 注册设置蓝图
└── docs/
    └── settings_api_implementation.md  # 本文档
```

### 关键代码

**路由注册 (app/__init__.py):**
```python
from routes.settings import settings_bp
app.register_blueprint(settings_bp)
```

**设置路由 (routes/settings.py):**
- `get_settings()`: 获取设置，不存在时创建默认设置
- `update_settings()`: 更新设置，包含参数验证
- `test_embedding()`: 测试嵌入模型连接

### 参数验证

所有更新操作都包含严格的参数验证：

1. **类型验证**: 确保参数类型正确（整数、浮点数等）
2. **范围验证**: 确保参数在有效范围内
3. **逻辑验证**: 确保参数值合理（如正整数、非负数等）

### 嵌入模型测试

测试接口支持两种 API 风格：

1. **OpenAI 风格**: `{model, input}`
2. **Ollama 风格**: `{model, prompt}`

测试流程：
1. 先尝试 OpenAI 风格
2. 如果失败，尝试 Ollama 风格
3. 返回成功的 API 风格和模型信息
4. 如果都失败，返回详细的错误信息

## 测试

### 运行测试

```bash
cd backend
python test_settings_routes.py
```

### 测试覆盖

测试文件 `test_settings_routes.py` 包含以下测试用例：

1. ✓ 获取设置（首次，应创建默认设置）
2. ✓ 更新设置
3. ✓ 再次获取设置（验证更新持久化）
4. ✓ 验证参数校验（无效的块大小）
5. ✓ 验证相似度阈值范围
6. ✓ 测试嵌入模型连接

所有测试均已通过。

## 数据库迁移

如果需要更新现有数据库的设置表结构，可以运行：

```bash
cd backend
python recreate_settings_table.py
```

**注意**: 这会删除并重新创建设置表，仅用于开发环境。生产环境应使用数据库迁移工具。

## 环境变量

相关的环境变量配置：

```env
# 嵌入模型配置
EMBEDDING_MODEL=nomic-embed-text
EMBEDDINGS_API_URL=http://127.0.0.1:11434/api/embeddings
```

## API 端点总结

| 方法 | 端点 | 描述 | 认证 |
|------|------|------|------|
| GET | /api/settings/knowledge-base | 获取知识库设置 | 需要 |
| PUT | /api/settings/knowledge-base | 更新知识库设置 | 需要 |
| POST | /api/settings/test-embedding | 测试嵌入模型连接 | 需要 |

## 相关需求

本实现满足以下需求：

- **需求 8.1**: 提供设置界面配置向量数据库连接参数
- **需求 8.2**: 支持选择嵌入模型
- **需求 8.3**: 支持配置文本块大小（chunk_size）
- **需求 8.4**: 支持配置文本块重叠大小（chunk_overlap）
- **需求 8.5**: 验证并保存配置更改
- **需求 3.5**: 提供向量数据库连接测试功能

## 后续工作

前端需要实现：
- 设置管理页面
- 嵌入模型测试界面
- 参数配置表单
- 实时验证反馈

## 更新日志

- 2025-11-12: 初始实现，包含所有设置管理 API 端点
