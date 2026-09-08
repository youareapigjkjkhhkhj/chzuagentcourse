# 知识库管理 API 实现文档

## 概述

本文档描述了知识库管理 API 的实现，包括知识库的 CRUD 操作和统计功能。

## 实现的接口

### 1. 获取知识库列表
- **路由**: `GET /api/kb`
- **功能**: 获取知识库列表，支持分页、搜索和状态过滤
- **查询参数**:
  - `page`: 页码（默认 1）
  - `per_page`: 每页数量（默认 20）
  - `search`: 搜索关键词（搜索名称和描述）
  - `status`: 状态过滤（active/archived）
- **响应**: 返回知识库列表和分页信息，每个知识库包含统计数据

### 2. 创建知识库
- **路由**: `POST /api/kb`
- **功能**: 创建新的知识库
- **请求体**:
  ```json
  {
    "name": "知识库名称",
    "description": "知识库描述",
    "embeddingModel": "嵌入模型名称",
    "status": "active"
  }
  ```
- **响应**: 返回创建的知识库信息

### 3. 获取知识库详情
- **路由**: `GET /api/kb/{kb_id}`
- **功能**: 获取指定知识库的详细信息
- **响应**: 返回知识库详情，包含统计数据

### 4. 更新知识库
- **路由**: `PUT /api/kb/{kb_id}`
- **功能**: 更新知识库信息
- **请求体**: 可包含 name, description, embeddingModel, status 字段
- **响应**: 返回更新后的知识库信息

### 5. 删除知识库
- **路由**: `DELETE /api/kb/{kb_id}`
- **功能**: 删除知识库及其所有文档和向量数据（级联删除）
- **响应**: 返回删除成功消息，包含删除的文档数量

### 6. 获取知识库统计信息
- **路由**: `GET /api/kb/{kb_id}/stats`
- **功能**: 获取知识库的详细统计信息
- **响应**: 返回以下统计数据：
  - `totalDocuments`: 总文档数
  - `publishedDocuments`: 已发布文档数
  - `draftDocuments`: 草稿文档数
  - `processingDocuments`: 处理中文档数
  - `failedDocuments`: 失败文档数
  - `totalVectors`: 总向量数
  - `categoryStats`: 按分类统计（对象）
  - `vectorStatusStats`: 按向量状态统计（对象）

## 技术实现

### 数据模型
使用 `KnowledgeBase` 模型，包含以下字段：
- `id`: 主键
- `name`: 知识库名称
- `description`: 描述
- `embedding_model`: 嵌入模型
- `status`: 状态（active/archived）
- `created_by`: 创建者
- `created_at`: 创建时间
- `updated_at`: 更新时间

### 关系
- 与 `Document` 模型一对多关系
- 级联删除：删除知识库时自动删除所有关联文档

### 认证
所有接口都需要登录认证（使用 `@login_required` 装饰器）

### 错误处理
- 400: 请求参数错误
- 401: 未认证
- 404: 知识库不存在
- 500: 服务器内部错误

## 使用示例

### 创建知识库
```bash
curl -X POST http://localhost:5000/api/kb \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "医学知识库",
    "description": "包含医学相关文档",
    "embeddingModel": "nomic-embed-text"
  }'
```

### 获取知识库列表
```bash
curl -X GET "http://localhost:5000/api/kb?page=1&per_page=10&search=医学" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 获取统计信息
```bash
curl -X GET http://localhost:5000/api/kb/{kb_id}/stats \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 需求覆盖

本实现覆盖了以下需求：
- 需求 1.1: 创建知识库功能
- 需求 1.2: 编辑知识库功能
- 需求 1.3: 删除知识库功能
- 需求 1.4: 列表展示和统计功能
- 需求 1.5: 搜索功能

## 注意事项

1. 删除知识库会级联删除所有关联的文档和向量数据，操作不可逆
2. 知识库名称为必填字段
3. 所有接口都返回统一的响应格式（success/error）
4. 分页默认每页 20 条记录
5. 搜索功能支持模糊匹配名称和描述字段
