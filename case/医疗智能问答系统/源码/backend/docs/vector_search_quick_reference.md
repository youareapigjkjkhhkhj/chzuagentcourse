# 向量化和搜索 API 快速参考

## 向量化接口

### 单文档向量化
```http
POST /api/kb/{kb_id}/documents/{doc_id}/vectorize
Authorization: Bearer {token}
Content-Type: application/json

{
  "force": false,
  "chunkSize": 1000,
  "chunkOverlap": 200
}
```

### 批量向量同步
```http
POST /api/kb/{kb_id}/sync-vectors
Authorization: Bearer {token}
Content-Type: application/json

{
  "force": false,
  "documentIds": [],
  "chunkSize": 1000,
  "chunkOverlap": 200
}
```

## 搜索接口

### 知识库内搜索
```http
POST /api/kb/{kb_id}/search
Authorization: Bearer {token}
Content-Type: application/json

{
  "query": "搜索关键词",
  "limit": 10,
  "searchType": "hybrid",
  "similarityThreshold": 0.7,
  "highlight": true
}
```

### 跨知识库搜索
```http
POST /api/kb/search
Authorization: Bearer {token}
Content-Type: application/json

{
  "query": "搜索关键词",
  "limit": 10,
  "searchType": "hybrid",
  "similarityThreshold": 0.7,
  "highlight": true,
  "kbIds": []
}
```

## 搜索类型

- `vector`: 纯向量相似度搜索（语义搜索）
- `sql`: 纯 SQL 全文搜索（关键词匹配）
- `hybrid`: 混合搜索（推荐，自动降级）

## 向量化状态

- `pending`: 待向量化
- `processing`: 处理中
- `completed`: 已完成
- `failed`: 失败

## 常用参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| force | boolean | false | 强制重新处理 |
| chunkSize | number | 1000 | 文本块大小 |
| chunkOverlap | number | 200 | 文本块重叠 |
| limit | number | 10 | 返回结果数 |
| similarityThreshold | number | 0.7 | 相似度阈值 |
| highlight | boolean | true | 高亮显示 |

## 响应格式

### 成功响应
```json
{
  "success": true,
  "message": "Success",
  "data": { ... }
}
```

### 错误响应
```json
{
  "success": false,
  "message": "错误描述",
  "error_code": null
}
```

## 状态码

- `200`: 成功
- `201`: 创建成功
- `400`: 请求参数错误
- `401`: 未认证
- `404`: 资源不存在
- `500`: 服务器错误
