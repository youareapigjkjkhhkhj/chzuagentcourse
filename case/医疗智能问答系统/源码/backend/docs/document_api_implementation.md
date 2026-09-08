# 文档管理 API 实现文档

## 概述

本文档描述了知识库文档管理 API 的实现，包括文档 CRUD、文件上传和批量操作功能。

## API 端点

### 1. 文档 CRUD 接口

#### 1.1 获取文档列表

**端点**: `GET /api/kb/{kb_id}/documents`

**描述**: 获取指定知识库的文档列表，支持分页、搜索和过滤

**请求参数**:
- `page` (可选): 页码，默认 1
- `per_page` (可选): 每页数量，默认 20
- `search` (可选): 搜索关键词（标题或内容）
- `status` (可选): 文档状态过滤（draft, processing, published, failed）
- `category` (可选): 分类过滤

**响应示例**:
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "documents": [
      {
        "id": "20241112001",
        "kbId": "kb001",
        "title": "示例文档",
        "content": "文档内容...",
        "category": "技术文档",
        "tags": ["Python", "API"],
        "author": "admin",
        "views": 10,
        "status": "published",
        "fileName": "example.pdf",
        "fileType": "pdf",
        "fileSize": 102400,
        "chunkCount": 5,
        "vectorStatus": "completed",
        "vectorError": null,
        "createdAt": "2024-11-12T10:00:00",
        "updatedAt": "2024-11-12T10:30:00"
      }
    ],
    "pagination": {
      "page": 1,
      "perPage": 20,
      "total": 50,
      "pages": 3,
      "hasNext": true,
      "hasPrev": false
    }
  }
}
```

#### 1.2 创建文档

**端点**: `POST /api/kb/{kb_id}/documents`

**描述**: 手动创建文档（录入文本内容）

**请求体**:
```json
{
  "title": "文档标题",
  "content": "文档内容",
  "category": "分类",
  "tags": ["标签1", "标签2"],
  "author": "作者",
  "status": "draft"
}
```

**必需字段**: `title`, `content`

**响应示例**:
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "message": "文档创建成功",
    "document": {
      "id": "20241112002",
      "kbId": "kb001",
      "title": "文档标题",
      ...
    }
  }
}
```

**说明**:
- 如果 `status` 为 `published`，系统会自动触发向量化处理
- 文档 ID 自动生成（时间戳格式）
- 作者默认为当前登录用户

#### 1.3 获取文档详情

**端点**: `GET /api/kb/{kb_id}/documents/{doc_id}`

**描述**: 获取指定文档的详细信息

**响应示例**:
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "document": {
      "id": "20241112001",
      "kbId": "kb001",
      "title": "示例文档",
      ...
    }
  }
}
```

**说明**:
- 每次访问会自动增加浏览次数（views）

#### 1.4 更新文档

**端点**: `PUT /api/kb/{kb_id}/documents/{doc_id}`

**描述**: 更新文档信息

**请求体**:
```json
{
  "title": "新标题",
  "content": "新内容",
  "category": "新分类",
  "tags": ["新标签"],
  "status": "published"
}
```

**响应示例**:
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "message": "文档更新成功",
    "document": {
      ...
    }
  }
}
```

**说明**:
- 如果状态从非 `published` 变为 `published`，会触发向量化
- 如果内容有变化且状态为 `published`，会重新向量化

#### 1.5 删除文档

**端点**: `DELETE /api/kb/{kb_id}/documents/{doc_id}`

**描述**: 删除指定文档

**响应示例**:
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "message": "文档已删除"
  }
}
```

**说明**:
- 删除文档时会自动删除关联的向量数据

### 2. 文件上传接口

#### 2.1 上传单个文件

**端点**: `POST /api/kb/{kb_id}/documents/upload`

**描述**: 上传单个文件并自动提取文本内容创建文档

**请求类型**: `multipart/form-data`

**请求参数**:
- `file` (必需): 上传的文件
- `category` (可选): 文档分类
- `tags` (可选): 标签数组的 JSON 字符串，如 `["标签1", "标签2"]`
- `status` (可选): 文档状态，默认 `draft`

**支持的文件格式**:
- txt
- md (Markdown)
- pdf
- docx
- xlsx
- pptx

**文件大小限制**: 50MB

**响应示例**:
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "message": "文件上传成功",
    "document": {
      "id": "20241112003",
      "kbId": "kb001",
      "title": "example",
      "content": "提取的文本内容...",
      "fileName": "example.pdf",
      "fileType": "pdf",
      "fileSize": 102400,
      ...
    }
  }
}
```

**错误响应**:
```json
{
  "success": false,
  "message": "文件大小超过限制 (50MB)",
  "error_code": null
}
```

**说明**:
- 文档标题默认使用文件名（不含扩展名）
- 上传后会自动提取文件中的文本内容
- 如果 `status` 为 `published`，会自动触发向量化
- 临时文件会在处理完成后自动清理

#### 2.2 上传 ZIP 批量导入

**端点**: `POST /api/kb/{kb_id}/documents/upload-zip`

**描述**: 上传 ZIP 压缩包，批量导入多个文件

**请求类型**: `multipart/form-data`

**请求参数**:
- `file` (必需): ZIP 压缩包
- `category` (可选): 所有文档的分类
- `tags` (可选): 所有文档的标签（JSON 字符串）
- `status` (可选): 所有文档的状态，默认 `draft`

**响应示例**:
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "message": "批量上传完成：成功 8 个，失败 2 个",
    "documents": [
      {
        "id": "20241112004",
        "title": "doc1",
        ...
      },
      ...
    ],
    "failedFiles": [
      {
        "fileName": "unsupported.exe",
        "error": "不支持的文件格式: exe"
      }
    ],
    "summary": {
      "total": 10,
      "success": 8,
      "failed": 2
    }
  }
}
```

**说明**:
- ZIP 文件中的所有支持格式的文件都会被处理
- 不支持的文件格式会被跳过，并在 `failedFiles` 中列出
- 隐藏文件（以 `.` 开头）和系统文件（以 `__` 开头）会被跳过
- 如果 `status` 为 `published`，所有成功创建的文档都会被向量化

### 3. 批量操作接口

#### 3.1 批量操作

**端点**: `POST /api/kb/{kb_id}/documents/batch`

**描述**: 对多个文档执行批量操作

**请求体**:
```json
{
  "operation": "publish",
  "documentIds": ["doc001", "doc002", "doc003"]
}
```

**支持的操作**:
- `delete`: 批量删除文档
- `publish`: 批量发布文档（状态改为 published）
- `draft`: 批量转为草稿（状态改为 draft）
- `sync-vectors`: 批量同步向量（重新向量化）

**响应示例**:
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "message": "批量发布完成：成功 3 个，失败 0 个",
    "summary": {
      "total": 3,
      "success": 3,
      "failed": 0
    },
    "errors": null
  }
}
```

**部分失败响应**:
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "message": "批量向量同步完成：成功 2 个，失败 1 个",
    "summary": {
      "total": 3,
      "success": 2,
      "failed": 1
    },
    "errors": [
      {
        "documentId": "doc003",
        "title": "文档3",
        "error": "文档未发布，跳过向量化"
      }
    ]
  }
}
```

**说明**:
- `delete` 操作会同时删除文档和关联的向量数据
- `publish` 操作会触发向量化（如果之前不是 published 状态）
- `sync-vectors` 操作只处理状态为 `published` 的文档
- 即使部分操作失败，成功的操作也会被提交

## 错误处理

### 常见错误码

| HTTP 状态码 | 错误场景 | 示例消息 |
|------------|---------|---------|
| 400 | 请求参数错误 | "缺少必需字段: title, content" |
| 400 | 文件格式不支持 | "不支持的文件格式。支持的格式: txt, md, pdf, docx, xlsx, pptx" |
| 401 | 未认证 | "缺少认证token" |
| 404 | 资源不存在 | "知识库不存在" |
| 413 | 文件过大 | "文件大小超过限制 (50MB)" |
| 422 | 文件解析失败 | "文件中未提取到任何文本内容" |
| 500 | 服务器错误 | "创建文档失败: ..." |

## 向量化处理

### 自动触发场景

1. **创建文档时**: 如果 `status` 为 `published`
2. **更新文档时**: 
   - 状态从非 `published` 变为 `published`
   - 内容有变化且状态为 `published`
3. **批量发布时**: 状态变为 `published` 的文档
4. **批量同步时**: 手动触发的向量同步操作

### 向量化流程

1. 文档状态设置为 `processing`
2. 使用 langchain 分割文本为块（chunk）
3. 为每个文本块生成嵌入向量
4. 将向量存储到 pgvector 数据库
5. 更新文档的 `chunk_count` 和 `vector_status`

### 向量状态

- `pending`: 等待向量化
- `processing`: 正在处理
- `completed`: 向量化完成
- `failed`: 向量化失败（错误信息存储在 `vector_error` 字段）

## 使用示例

### Python 示例

```python
import requests

# 基础 URL
base_url = "http://localhost:5000/api/kb"
kb_id = "kb001"
token = "your-jwt-token"

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

# 1. 创建文档
doc_data = {
    "title": "Python 教程",
    "content": "这是一个 Python 教程...",
    "category": "编程",
    "tags": ["Python", "教程"],
    "status": "published"
}
response = requests.post(
    f"{base_url}/{kb_id}/documents",
    json=doc_data,
    headers=headers
)
print(response.json())

# 2. 上传文件
files = {"file": open("document.pdf", "rb")}
data = {
    "category": "技术文档",
    "tags": '["PDF", "文档"]',
    "status": "draft"
}
response = requests.post(
    f"{base_url}/{kb_id}/documents/upload",
    files=files,
    data=data,
    headers={"Authorization": f"Bearer {token}"}
)
print(response.json())

# 3. 批量发布
batch_data = {
    "operation": "publish",
    "documentIds": ["doc001", "doc002", "doc003"]
}
response = requests.post(
    f"{base_url}/{kb_id}/documents/batch",
    json=batch_data,
    headers=headers
)
print(response.json())
```

### cURL 示例

```bash
# 创建文档
curl -X POST "http://localhost:5000/api/kb/kb001/documents" \
  -H "Authorization: Bearer your-jwt-token" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "测试文档",
    "content": "文档内容",
    "status": "published"
  }'

# 上传文件
curl -X POST "http://localhost:5000/api/kb/kb001/documents/upload" \
  -H "Authorization: Bearer your-jwt-token" \
  -F "file=@document.pdf" \
  -F "category=技术文档" \
  -F "status=draft"

# 批量删除
curl -X POST "http://localhost:5000/api/kb/kb001/documents/batch" \
  -H "Authorization: Bearer your-jwt-token" \
  -H "Content-Type: application/json" \
  -d '{
    "operation": "delete",
    "documentIds": ["doc001", "doc002"]
  }'
```

## 性能考虑

1. **分页**: 文档列表默认每页 20 条，建议根据实际需求调整
2. **向量化**: 大文档的向量化可能需要较长时间，建议异步处理
3. **批量操作**: 批量操作会逐个处理文档，大量文档可能需要较长时间
4. **文件上传**: 大文件上传和解析可能需要较长时间，建议设置合理的超时时间

## 安全考虑

1. **认证**: 所有接口都需要 JWT token 认证
2. **文件验证**: 上传的文件会进行格式和大小验证
3. **文件名安全**: 使用 `secure_filename` 处理文件名，防止路径遍历攻击
4. **临时文件清理**: 上传的临时文件会在处理完成后自动清理
5. **SQL 注入防护**: 使用 SQLAlchemy ORM 参数化查询

## 测试

运行测试脚本验证实现:

```bash
cd backend
python test_document_routes.py
```

测试覆盖:
- ✓ 文档 CRUD 操作
- ✓ 批量创建和删除
- ✓ 状态更新
- ✓ 文档统计

## 相关文档

- [知识库管理 API](./kb_api_implementation.md)
- [文件处理器实现](./file_processor_implementation.md)
- [向量管理器实现](./vector_manager_implementation.md)
- [数据库架构](./database_schema.md)
