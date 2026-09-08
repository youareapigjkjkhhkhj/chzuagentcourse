# 设置管理 API 快速参考

## API 端点

### 1. 获取设置
```
GET /api/settings/knowledge-base
```

**响应字段：**
- `vectorDbType`: 向量数据库类型（默认: "pgvector"）
- `connectionString`: 数据库连接字符串
- `embeddingModel`: 嵌入模型名称
- `embeddingDimension`: 向量维度（默认: 1536）
- `chunkSize`: 文本块大小（默认: 1000）
- `chunkOverlap`: 文本块重叠（默认: 200）
- `similarityThreshold`: 相似度阈值（默认: 0.7）
- `maxSearchResults`: 最大搜索结果数（默认: 10）

---

### 2. 更新设置
```
PUT /api/settings/knowledge-base
```

**请求体（所有字段可选）：**
```json
{
  "vectorDbType": "pgvector",
  "connectionString": "postgresql://...",
  "embeddingModel": "text-embedding-3-small",
  "embeddingDimension": 768,
  "chunkSize": 1500,
  "chunkOverlap": 300,
  "similarityThreshold": 0.8,
  "maxSearchResults": 20
}
```

**验证规则：**
- `embeddingDimension` > 0
- `chunkSize` > 0
- `chunkOverlap` >= 0
- `0 <= similarityThreshold <= 1`
- `maxSearchResults` > 0

---

### 3. 测试嵌入模型
```
POST /api/settings/test-embedding
```

**请求体（所有字段可选）：**
```json
{
  "embeddingModel": "nomic-embed-text",
  "embeddingApiUrl": "http://127.0.0.1:11434/api/embeddings",
  "testText": "测试文本"
}
```

**响应（成功）：**
```json
{
  "available": true,
  "model": "nomic-embed-text",
  "dimension": 768,
  "apiStyle": "Ollama"
}
```

**响应（失败）：**
```json
{
  "available": false,
  "error": "无法连接到 API，请检查服务是否运行"
}
```

---

## 使用示例

### Python
```python
import requests

# 获取设置
response = requests.get(
    'http://localhost:5000/api/settings/knowledge-base',
    headers={'Authorization': 'Bearer YOUR_TOKEN'}
)
settings = response.json()['data']['settings']

# 更新设置
response = requests.put(
    'http://localhost:5000/api/settings/knowledge-base',
    headers={
        'Authorization': 'Bearer YOUR_TOKEN',
        'Content-Type': 'application/json'
    },
    json={
        'chunkSize': 1500,
        'chunkOverlap': 300
    }
)

# 测试嵌入模型
response = requests.post(
    'http://localhost:5000/api/settings/test-embedding',
    headers={
        'Authorization': 'Bearer YOUR_TOKEN',
        'Content-Type': 'application/json'
    },
    json={
        'embeddingModel': 'nomic-embed-text'
    }
)
```

### JavaScript/TypeScript
```typescript
// 获取设置
const getSettings = async () => {
  const response = await fetch('/api/settings/knowledge-base', {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });
  const data = await response.json();
  return data.data.settings;
};

// 更新设置
const updateSettings = async (settings) => {
  const response = await fetch('/api/settings/knowledge-base', {
    method: 'PUT',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(settings)
  });
  return await response.json();
};

// 测试嵌入模型
const testEmbedding = async (config) => {
  const response = await fetch('/api/settings/test-embedding', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(config)
  });
  return await response.json();
};
```

---

## 常见错误

| 状态码 | 错误信息 | 解决方法 |
|--------|----------|----------|
| 400 | 文本块大小必须是正整数 | 确保 chunkSize > 0 |
| 400 | 相似度阈值必须在0到1之间 | 确保 0 <= similarityThreshold <= 1 |
| 401 | token已过期或无效 | 重新登录获取新 token |
| 500 | 获取设置失败 | 检查数据库连接 |

---

## 默认配置

```json
{
  "vectorDbType": "pgvector",
  "embeddingModel": "nomic-embed-text",
  "embeddingDimension": 1536,
  "chunkSize": 1000,
  "chunkOverlap": 200,
  "similarityThreshold": 0.7,
  "maxSearchResults": 10
}
```
