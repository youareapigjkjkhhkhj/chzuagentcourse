# 知识库 CRUD API 实现文档

## 概述

本文档描述了知识库管理系统的 CRUD API 实现，包括创建、读取、更新和删除知识库的功能。

## 实现的接口

### 1. 获取知识库列表
- **路由**: `GET /api/kb`
- **功能**: 获取知识库列表，支持分页、搜索和状态过滤
- **查询参数**:
  - `page`: 页码（默认: 1）
  - `per_page`: 每页数量（默认: 20）
  - `search`: 搜索关键词（可选）
  - `status`: 状态过滤（可选）
- **响应**: 返回知识库列表和分页信息

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
- **响应**: 返回知识库详情，包括统计信息

### 4. 更新知识库
- **路由**: `PUT /api/kb/{kb_id}`
- **功能**: 更新知识库信息
- **请求体**:
  ```json
  {
    "name": "新名称",
    "description": "新描述",
    "embeddingModel": "新模型",
    "status": "active"
  }
  ```
- **响应**: 返回更新后的知识库信息

### 5. 删除知识库
- **路由**: `DELETE /api/kb/{kb_id}`
- **功能**: 删除知识库及其所有文档和向量数据（级联删除）
- **响应**: 返回删除成功消息

### 6. 获取知识库统计信息
- **路由**: `GET /api/kb/{kb_id}/stats`
- **功能**: 获取知识库的详细统计信息
- **响应**: 返回文档数量、向量数量、分类统计等信息

## 数据模型

### KnowledgeBase 模型

```python
class KnowledgeBase(db.Model):
    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    embedding_model = db.Column(db.String(100))
    status = db.Column(db.String(20), default='active')
    created_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)
```

## 认证和授权

所有接口都需要用户认证，使用 `@login_required` 装饰器保护。

## 错误处理

- **400**: 请求参数错误
- **401**: 未认证
- **404**: 知识库不存在
- **500**: 服务器内部错误

## 文件结构

```
backend/
├── routes/
│   └── kb.py                    # 知识库路由实现
├── models/
│   └── knowledge_base.py        # 知识库模型
├── utils/
│   ├── response.py              # 响应工具函数
│   └── auth.py                  # 认证工具函数
└── app/
    └── __init__.py              # 应用初始化（注册蓝图）
```

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
curl -X GET "http://localhost:5000/api/kb?page=1&per_page=20" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 更新知识库

```bash
curl -X PUT http://localhost:5000/api/kb/KB_ID \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "更新后的名称",
    "description": "更新后的描述"
  }'
```

### 删除知识库

```bash
curl -X DELETE http://localhost:5000/api/kb/KB_ID \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 实现要点

1. **分页支持**: 使用 SQLAlchemy 的 `paginate()` 方法实现分页
2. **搜索功能**: 支持按名称和描述搜索
3. **级联删除**: 删除知识库时自动删除关联的文档和向量
4. **统计信息**: 提供文档数量、向量数量等统计数据
5. **错误处理**: 完善的异常捕获和错误响应
6. **日志记录**: 记录所有操作的详细日志

## 测试

运行验证脚本确认实现：

```bash
cd backend
python verify_kb_implementation.py
```

## 相关需求

本实现满足以下需求：
- 需求 1.1: 创建知识库功能
- 需求 1.2: 编辑知识库功能
- 需求 1.3: 删除知识库功能
- 需求 1.4: 列表展示和统计功能
- 需求 1.5: 搜索功能
