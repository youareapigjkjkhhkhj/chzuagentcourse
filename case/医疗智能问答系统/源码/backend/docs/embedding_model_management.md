# 嵌入模型管理说明

## 概述

系统支持两种方式配置嵌入模型：
1. **推荐方式**：在"模型管理"页面配置向量模型
2. **回退方式**：使用 `.env` 文件中的默认配置

## 工作原理

### 优先级顺序

1. **模型管理中的向量模型**（最高优先级）
   - 在"模型管理"页面添加 `type=embedding` 的模型
   - 配置模型的 API 端点
   - 在"知识库设置"中选择该模型

2. **.env 中的默认模型**（回退）
   - 如果模型管理中没有向量模型
   - 或者数据库中没有保存设置
   - 系统会使用 `.env` 中的配置

### 嵌入模型下拉列表

"知识库设置"页面的嵌入模型下拉列表：
- **只显示模型管理中 `type=embedding` 的模型**
- 如果当前保存的模型不在列表中（通常是 .env 的默认模型），会自动添加到列表顶部
- 显示格式：`模型名称 (提供商)`
  - 例如：`bge-m3:latest (ollama)`
  - 默认模型：`bge-m3:latest (default (.env))`

## 配置步骤

### 方式一：使用模型管理（推荐）

1. **添加向量模型**
   ```
   进入"模型管理"页面
   点击"添加模型"
   填写信息：
   - 模型名称：bge-m3:latest
   - 提供商：ollama
   - 类型：embedding（向量模型）
   - API 端点：http://your-server.com
   - 状态：active
   ```

2. **在知识库设置中选择**
   ```
   进入"知识库设置"
   在"嵌入模型"下拉列表中选择刚添加的模型
   系统会自动填充 API URL
   点击"保存"
   ```

3. **测试模型**
   ```
   点击"测试嵌入模型连接"按钮
   查看测试结果
   ```

### 方式二：使用 .env 配置（回退）

编辑 `backend/.env` 文件：

```bash
# 嵌入模型配置（默认模型）
EMBEDDING_MODEL=bge-m3:latest
EMBEDDING_DIMENSION=1024
EMBEDDINGS_API_URL=http://your-server.com/api/embeddings
```

**注意**：
- 这是回退配置，优先使用模型管理中的配置
- 如果模型管理中有向量模型，这里的配置会被忽略
- 只有在没有其他配置时才会使用

## 数据流程

### 创建默认设置时

```python
# backend/routes/settings.py

# 1. 从 .env 获取默认模型名称
default_embedding_model = os.getenv('EMBEDDING_MODEL', 'nomic-embed-text')

# 2. 尝试从模型配置中获取 API URL
model_config = ModelConfig.query.filter_by(
    model_name=default_embedding_model,
    type='embedding'
).first()

if model_config and model_config.api_endpoint:
    embedding_api_url = model_config.api_endpoint
else:
    # 3. 回退到 .env 中的 API URL
    embedding_api_url = os.getenv('EMBEDDINGS_API_URL')

# 4. 创建设置
settings = KnowledgeBaseSettings(
    embedding_model=default_embedding_model,
    embedding_api_url=embedding_api_url,
    # ...
)
```

### 前端加载模型列表

```typescript
// frotend/src/pages/KnowledgeBase.tsx

// 1. 从 API 获取所有模型
const allModels = await modelAPI.getModels();

// 2. 只保留向量模型
const embeddingModels = allModels.filter(
  model => model.type === ModelType.EMBEDDING
);

// 3. 如果当前保存的模型不在列表中，添加它
const savedModel = settings.embeddingModel;
if (savedModel && !embeddingModels.some(m => m.modelName === savedModel)) {
  embeddingModels.unshift({
    modelName: savedModel,
    provider: 'default (.env)',  // 标记为默认模型
    type: ModelType.EMBEDDING,
    apiEndpoint: settings.embeddingApiUrl || ''
  });
}
```

### 选择模型时

```typescript
// 用户选择模型
onChange={(e) => {
  const selectedModelName = e.target.value;
  const selectedModel = embeddingModels.find(m => m.modelName === selectedModelName);
  
  // 自动获取 API URL
  let apiUrl = '';
  if (selectedModel && selectedModel.apiEndpoint) {
    apiUrl = selectedModel.apiEndpoint;
    if (!apiUrl.endsWith('/api/embeddings')) {
      apiUrl = `${apiUrl}/api/embeddings`;
    }
  }
  
  // 更新设置
  setVectorDbSettings({
    ...prev,
    embeddingModel: selectedModelName,
    embeddingApiUrl: apiUrl
  });
}}
```

## 模型管理 API

### 添加向量模型

```bash
POST /api/models
Content-Type: application/json
Authorization: Bearer <token>

{
  "name": "bge-m3:latest",
  "provider": "ollama",
  "type": "embedding",
  "modelName": "bge-m3:latest",
  "apiEndpoint": "http://your-server.com",
  "status": "active",
  "description": "BGE-M3 嵌入模型"
}
```

### 获取向量模型列表

```bash
GET /api/models?type=embedding
Authorization: Bearer <token>
```

响应：
```json
{
  "success": true,
  "data": {
    "models": [
      {
        "id": "20251111064240677",
        "name": "bge-m3:latest",
        "provider": "ollama",
        "type": "embedding",
        "modelName": "bge-m3:latest",
        "apiEndpoint": "http://20e5af39.r30.cpolar.top",
        "status": "active",
        "isDefault": false
      }
    ]
  }
}
```

## 环境变量说明

### backend/.env

```bash
# ============================================
# 嵌入模型配置（默认模型）
# ============================================
# 注意：这些是默认值，优先使用"模型管理"中配置的向量模型
# 如果"模型管理"中没有配置向量模型，将使用这里的默认值

# 默认嵌入模型名称
EMBEDDING_MODEL=bge-m3:latest

# 默认向量维度
EMBEDDING_DIMENSION=1024

# 默认嵌入服务 API 地址
EMBEDDINGS_API_URL=http://127.0.0.1:11434/api/embeddings

# ============================================
# 推荐做法：
# ============================================
# 1. 在"模型管理"页面添加向量模型（type=embedding）
# 2. 配置模型的 API 端点
# 3. 在"知识库设置"中选择该模型
# 4. 系统会自动使用模型管理中的配置
```

## 常见场景

### 场景 1：首次使用

1. 系统启动时，数据库中没有设置
2. 系统使用 `.env` 中的 `EMBEDDING_MODEL` 创建默认设置
3. 尝试从模型管理中查找该模型的 API 端点
4. 如果找不到，使用 `.env` 中的 `EMBEDDINGS_API_URL`

### 场景 2：添加新的向量模型

1. 用户在"模型管理"中添加新的向量模型
2. 配置 API 端点：`http://new-server.com`
3. 在"知识库设置"中选择新模型
4. 系统自动填充 API URL：`http://new-server.com/api/embeddings`
5. 保存设置

### 场景 3：切换模型

1. 用户在"知识库设置"中选择不同的模型
2. 系统自动更新 API URL
3. 点击"测试嵌入模型连接"验证
4. 保存设置

### 场景 4：模型不在列表中

1. 数据库中保存的模型是 `.env` 中的默认模型
2. 但模型管理中没有该模型
3. 系统自动将该模型添加到下拉列表顶部
4. 显示为：`模型名称 (default (.env))`
5. 使用数据库中保存的 API URL

## 优势

1. **集中管理**：所有模型在"模型管理"页面统一配置
2. **自动化**：选择模型时自动获取 API 端点
3. **灵活性**：支持多个向量模型，可以随时切换
4. **回退机制**：如果模型管理中没有配置，使用 .env 默认值
5. **用户友好**：界面上显示当前使用的 API URL

## 故障排查

### 问题：嵌入模型不可用

**检查步骤**：

1. **检查模型管理**
   ```
   进入"模型管理"页面
   确认有 type=embedding 的模型
   检查 API 端点是否正确
   ```

2. **检查知识库设置**
   ```
   进入"知识库设置"
   查看选中的嵌入模型
   查看显示的 API URL
   点击"测试嵌入模型连接"
   ```

3. **检查 .env 配置**
   ```bash
   cat backend/.env | grep EMBEDDING
   ```

4. **检查数据库**
   ```sql
   SELECT embedding_model, embedding_api_url 
   FROM knowledge_base_settings 
   WHERE id = 'default';
   ```

### 问题：连接本地地址而不是配置的地址

**原因**：
- 模型管理中没有配置该模型
- 或者 API 端点为空
- 系统回退到 .env 中的默认地址

**解决方案**：
1. 在"模型管理"中添加该模型
2. 配置正确的 API 端点
3. 在"知识库设置"中重新选择该模型
4. 保存设置

## 相关文件

- `backend/models/settings.py` - 设置数据模型
- `backend/routes/settings.py` - 设置管理路由
- `backend/models/model.py` - 模型配置数据模型
- `backend/routes/models.py` - 模型管理路由
- `frotend/src/pages/KnowledgeBase.tsx` - 知识库设置页面
- `frotend/src/pages/ModelManagement.tsx` - 模型管理页面
- `backend/.env` - 环境变量配置
