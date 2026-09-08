# 文档管理 API 快速参考

## 文档 CRUD

```bash
# 获取文档列表
GET /api/kb/{kb_id}/documents?page=1&per_page=20&search=关键词&status=published

# 创建文档
POST /api/kb/{kb_id}/documents
{
  "title": "标题",
  "content": "内容",
  "category": "分类",
  "tags": ["标签1"],
  "status": "draft"
}

# 获取文档详情
GET /api/kb/{kb_id}/documents/{doc_id}

# 更新文档
PUT /api/kb/{kb_id}/documents/{doc_id}
{
  "title": "新标题",
  "content": "新内容",
  "status": "published"
}

# 删除文档
DELETE /api/kb/{kb_id}/documents/{doc_id}
```

## 文件上传

```bash
# 上传单文件
POST /api/kb/{kb_id}/documents/upload
Content-Type: multipart/form-data
- file: [文件]
- category: "分类"
- tags: '["标签1", "标签2"]'
- status: "draft"

# 上传 ZIP
POST /api/kb/{kb_id}/documents/upload-zip
Content-Type: multipart/form-data
- file: [ZIP文件]
- category: "分类"
- tags: '["标签1"]'
- status: "draft"
```

## 批量操作

```bash
# 批量删除
POST /api/kb/{kb_id}/documents/batch
{
  "operation": "delete",
  "documentIds": ["doc1", "doc2"]
}

# 批量发布
POST /api/kb/{kb_id}/documents/batch
{
  "operation": "publish",
  "documentIds": ["doc1", "doc2"]
}

# 批量转草稿
POST /api/kb/{kb_id}/documents/batch
{
  "operation": "draft",
  "documentIds": ["doc1", "doc2"]
}

# 批量向量同步
POST /api/kb/{kb_id}/documents/batch
{
  "operation": "sync-vectors",
  "documentIds": ["doc1", "doc2"]
}
```

## 支持的文件格式

- txt
- md (Markdown)
- pdf
- docx
- xlsx
- pptx

## 文档状态

- `draft` - 草稿
- `processing` - 处理中
- `published` - 已发布
- `failed` - 失败

## 向量状态

- `pending` - 等待向量化
- `processing` - 正在处理
- `completed` - 完成
- `failed` - 失败

## 认证

所有接口需要 JWT token：

```
Authorization: Bearer {token}
```
