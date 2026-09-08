# 知识库设置端点修复总结

## 问题描述

在清理旧的 Weaviate 代码后，发现知识库设置功能出现问题：
1. 前端调用的是旧的 `/api/knowledge/settings` 端点，但该端点已被删除
2. 数据库中 `connection_string` 字段为空
3. 嵌入模型显示不可用

## 根本原因

1. **端点不匹配**：前端 `knowledgeAPI` 还在调用旧的 `/api/knowledge/*` 端点
2. **路由已删除**：`backend/routes/knowledge.py` 已被删除，所有旧端点不再可用
3. **新端点未使用**：新的设置端点 `/api/settings/knowledge-base` 已实现但前端未使用

## 修复内容

### 1. 更新前端 API 调用 (frotend/src/services/api.ts)

#### 修改前：
```typescript
// 获取知识库设置
getSettings: async () => {
  const res = await apiRequest('/knowledge/settings');
  return res;
},

// 更新知识库设置
updateSettings: async (settings) => {
  const res = await apiRequest('/knowledge/settings', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  return res;
},
```

#### 修改后：
```typescript
// 获取知识库设置
getSettings: async () => {
  const res = await apiRequest('/settings/knowledge-base');
  return res;
},

// 更新知识库设置
updateSettings: async (settings) => {
  const res = await apiRequest('/settings/knowledge-base', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  return res;
},

// 新增：测试嵌入模型连接
testEmbedding: async (params?) => {
  const res = await apiRequest('/settings/test-embedding', {
    method: 'POST',
    body: JSON.stringify(params || {}),
  });
  return res;
},
```

### 2. 更新设置路由 (backend/routes/settings.py)

#### 修改：创建默认设置时包含 connection_string
```python
# 如果不存在，创建默认设置
if not settings:
    # 使用环境变量中的数据库连接字符串
    db_url = os.getenv('DATABASE_URL', '')
    settings = KnowledgeBaseSettings(
        id='default',
        vector_db_type='pgvector',
        connection_string=db_url,  # 使用主数据库连接
        embedding_model=os.getenv('EMBEDDING_MODEL', 'nomic-embed-text'),
        embedding_dimension=1536,
        chunk_size=1000,
        chunk_overlap=200,
        similarity_threshold=0.7,
        max_search_results=10
    )
```

### 3. 更新前端 UI (frotend/src/pages/KnowledgeBase.tsx)

#### 修改 1：更新测试连接功能
- 从测试向量数据库连接改为测试嵌入模型连接
- 使用新的 `testEmbedding` API

```typescript
// 测试嵌入模型连接
const handleTestConnection = async () => {
  if (!vectorDbSettings.embeddingModel) {
    alert('请先选择嵌入模型');
    return;
  }
  
  const response = await knowledgeAPI.testEmbedding({
    embeddingModel: vectorDbSettings.embeddingModel
  });
  
  const testResult = response?.data ?? {};
  const available = !!testResult.available;
  
  if (available) {
    alert(`嵌入模型测试成功！\n模型: ${testResult.model}\n维度: ${testResult.dimension}`);
  } else {
    alert(`嵌入模型测试失败：${testResult.error}`);
  }
};
```

#### 修改 2：连接字符串字段改为只读
```typescript
<input
  type="text"
  id="connectionString"
  value={vectorDbSettings.connectionString}
  readOnly
  className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-gray-50 text-gray-600"
  placeholder="使用主数据库连接"
/>
<p className="text-xs text-gray-500 mt-1">
  pgvector 使用与主数据库相同的连接（由后端配置）
</p>
```

#### 修改 3：添加独立的嵌入模型测试按钮
```typescript
<div>
  <label className="block text-sm font-medium text-gray-700 mb-1">
    嵌入模型测试
  </label>
  <button
    type="button"
    onClick={handleTestConnection}
    disabled={testingConnection || !vectorDbSettings.embeddingModel}
    className="w-full px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700"
  >
    测试嵌入模型连接
  </button>
</div>
```

#### 修改 4：禁用旧的向量同步功能
```typescript
const handleSyncVectors = async (_force: boolean = false, _selectedIds?: string[]) => {
  alert('此功能已迁移到新的知识库系统。\n\n请使用"知识库管理"页面来：\n1. 创建知识库\n2. 上传文档\n3. 自动向量化\n4. 进行语义搜索');
};
```

### 4. 添加新的向量同步 API (frotend/src/services/api.ts)

为新的知识库系统添加向量同步 API：

```typescript
// 批量同步知识库向量
syncKbVectors: async (kbId: string, params?: {
  force?: boolean;
  documentIds?: string[];
}) => {
  return await apiRequest(`/kb/${kbId}/sync-vectors`, {
    method: 'POST',
    body: JSON.stringify(params || {}),
  });
},
```

## API 端点对照表

| 功能 | 旧端点 (已删除) | 新端点 |
|------|----------------|--------|
| 获取设置 | GET /api/knowledge/settings | GET /api/settings/knowledge-base |
| 更新设置 | PUT /api/knowledge/settings | PUT /api/settings/knowledge-base |
| 测试连接 | POST /api/knowledge/test-connection | POST /api/settings/test-embedding |
| 创建集合 | POST /api/knowledge/create-collection | ❌ 不再需要（pgvector 自动管理） |
| 同步向量 | POST /api/knowledge/sync-vectors | POST /api/kb/{kb_id}/sync-vectors |

## 数据库字段说明

### KnowledgeBaseSettings 表

| 字段 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| id | String(50) | 主键 | 'default' |
| vector_db_type | String(50) | 向量数据库类型 | 'pgvector' |
| connection_string | String(500) | 数据库连接字符串 | DATABASE_URL 环境变量 |
| embedding_model | String(100) | 嵌入模型 | 'nomic-embed-text' |
| embedding_dimension | Integer | 向量维度 | 1536 |
| chunk_size | Integer | 文本块大小 | 1000 |
| chunk_overlap | Integer | 文本块重叠 | 200 |
| similarity_threshold | Float | 相似度阈值 | 0.7 |
| max_search_results | Integer | 最大搜索结果数 | 10 |

## 环境变量配置

### 必需的环境变量

```bash
# 数据库连接（PostgreSQL with pgvector）
DATABASE_URL=postgresql://user:password@localhost:5432/dbname

# 嵌入模型配置
EMBEDDING_MODEL=nomic-embed-text
EMBEDDINGS_API_URL=http://127.0.0.1:11434/api/embeddings
```

### 可选的环境变量

```bash
# OpenAI API（如果使用 OpenAI 嵌入模型）
OPENAI_API_KEY=sk-...
```

## 测试步骤

1. **启动后端服务**
   ```bash
   cd backend
   python run.py
   ```

2. **访问知识库设置页面**
   - 打开前端应用
   - 进入"知识库"页面
   - 点击"设置"按钮

3. **验证设置加载**
   - 检查是否显示当前设置
   - 连接字符串应显示为只读
   - 嵌入模型下拉列表应有选项

4. **测试嵌入模型**
   - 选择一个嵌入模型
   - 点击"测试嵌入模型连接"按钮
   - 应显示测试结果（成功/失败）

5. **保存设置**
   - 修改设置（如 chunk_size）
   - 点击"保存"按钮
   - 应显示"设置已保存"消息

## 已知限制

1. **旧的文章系统**：`KnowledgeBase.tsx` 页面使用的是旧的 `knowledge_articles` 表，不是新的知识库+文档系统
2. **向量同步**：旧页面的向量同步功能已禁用，用户需要使用新的"知识库管理"页面
3. **连接字符串**：pgvector 使用主数据库连接，不支持单独配置

## 迁移建议

建议用户从旧的文章系统迁移到新的知识库系统：

1. **创建知识库**：在"知识库管理"页面创建新的知识库
2. **导入文档**：将旧文章内容导出并重新导入为文档
3. **自动向量化**：新系统会自动处理文档向量化
4. **使用新功能**：享受更好的文档管理和搜索体验

## 相关文件

- `backend/routes/settings.py` - 设置管理路由
- `backend/models/settings.py` - 设置数据模型
- `frotend/src/services/api.ts` - API 调用封装
- `frotend/src/pages/KnowledgeBase.tsx` - 旧的知识库页面
- `frotend/src/pages/KnowledgeBaseList.tsx` - 新的知识库列表页面
- `frotend/src/pages/KnowledgeBaseSettings.tsx` - 新的知识库设置页面
