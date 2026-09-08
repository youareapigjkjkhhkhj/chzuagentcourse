# 嵌入模型 API URL 自动配置修复

## 问题描述

用户报告的问题：
1. 测试嵌入模型时连接的是本地地址 `http://127.0.0.1:11434/api/embeddings`，而不是模型配置中的地址
2. 数据库中的 `connection_string` 字段为空
3. 保存设置时没有把模型的 API 端点保存进去
4. 用户希望能从"模型管理"中选择向量模型，并自动使用其配置的端点

## 根本原因

1. **硬编码的 API URL**：测试嵌入模型时使用环境变量或硬编码的本地地址，没有从模型配置中获取
2. **缺少字段**：`knowledge_base_settings` 表缺少 `embedding_api_url` 字段
3. **前端未传递**：前端选择模型时没有获取和传递模型的 API 端点
4. **后端未保存**：后端保存设置时没有处理 `embeddingApiUrl` 字段

## 解决方案

### 1. 数据库模型更新

#### 添加字段到 KnowledgeBaseSettings 模型

```python
# backend/models/settings.py

class KnowledgeBaseSettings(db.Model):
    # ... 其他字段 ...
    
    # 嵌入模型设置
    embedding_model = db.Column(db.String(100), default='text-embedding-3-small', comment='嵌入模型')
    embedding_api_url = db.Column(db.String(500), comment='嵌入模型 API 地址')  # 新增
    embedding_dimension = db.Column(db.Integer, default=1536, comment='向量维度')
```

#### 更新 to_dict 和 from_dict 方法

```python
def to_dict(self):
    return {
        # ... 其他字段 ...
        'embeddingModel': self.embedding_model,
        'embeddingApiUrl': self.embedding_api_url,  # 新增
        'embeddingDimension': self.embedding_dimension,
        # ... 其他字段 ...
    }

@classmethod
def from_dict(cls, data):
    settings = cls()
    # ... 其他字段 ...
    if 'embeddingApiUrl' in data:
        settings.embedding_api_url = data['embeddingApiUrl']  # 新增
    # ... 其他字段 ...
    return settings
```

### 2. 后端路由更新

#### 更新设置保存逻辑

```python
# backend/routes/settings.py

@settings_bp.route('/knowledge-base', methods=['PUT'])
@login_required
def update_settings():
    # ... 其他代码 ...
    
    if 'embeddingModel' in data:
        settings.embedding_model = data['embeddingModel']
        
        # 如果更改了嵌入模型，尝试从模型配置中获取 API URL
        if 'embeddingApiUrl' not in data:
            try:
                from models.model import ModelConfig
                model_config = ModelConfig.query.filter_by(
                    model_name=data['embeddingModel'],
                    type='embedding'
                ).first()
                
                if model_config and model_config.api_endpoint:
                    api_url = model_config.api_endpoint
                    # 确保 URL 包含 /api/embeddings 路径
                    if not api_url.endswith('/api/embeddings') and not api_url.endswith('/embeddings'):
                        api_url = f"{api_url}/api/embeddings"
                    settings.embedding_api_url = api_url
            except Exception as model_err:
                logger.warning(f"Failed to get model config: {model_err}")
    
    if 'embeddingApiUrl' in data:
        settings.embedding_api_url = data['embeddingApiUrl']
```

#### 更新测试嵌入模型逻辑

```python
@settings_bp.route('/test-embedding', methods=['POST'])
@login_required
def test_embedding():
    # ... 获取参数 ...
    
    # 如果没有 API URL，尝试从模型配置中获取
    if embedding_model and not embedding_api_url:
        try:
            from models.model import ModelConfig
            model_config = ModelConfig.query.filter_by(
                model_name=embedding_model,
                type='embedding'
            ).first()
            
            if model_config and model_config.api_endpoint:
                embedding_api_url = model_config.api_endpoint
                # 确保 URL 包含 /api/embeddings 路径
                if not embedding_api_url.endswith('/api/embeddings'):
                    embedding_api_url = f"{embedding_api_url}/api/embeddings"
        except Exception as model_err:
            logger.warning(f"Failed to get model config: {model_err}")
    
    # 最后的回退：使用环境变量
    if not embedding_api_url:
        embedding_api_url = os.getenv('EMBEDDINGS_API_URL', 'http://127.0.0.1:11434/api/embeddings')
```

### 3. 前端更新

#### 更新 VectorDbSettings 接口

```typescript
// frotend/src/pages/KnowledgeBase.tsx

interface VectorDbSettings {
  type: VectorDbType;
  embeddingModel: string;
  embeddingApiUrl?: string;  // 新增
  chunkSize: number;
  chunkOverlap: number;
  connectionString: string;
}
```

#### 更新嵌入模型选择逻辑

```typescript
<select
  id="embeddingModel"
  value={vectorDbSettings.embeddingModel}
  onChange={(e) => {
    const selectedModelName = e.target.value;
    const selectedModel = embeddingModels.find(m => m.modelName === selectedModelName);
    
    // 自动设置 API URL
    let apiUrl = '';
    if (selectedModel && selectedModel.apiEndpoint) {
      apiUrl = selectedModel.apiEndpoint;
      // 确保 URL 包含 /api/embeddings 路径
      if (!apiUrl.endsWith('/api/embeddings') && !apiUrl.endsWith('/embeddings')) {
        apiUrl = `${apiUrl}/api/embeddings`;
      }
    }
    
    setVectorDbSettings(prev => ({ 
      ...prev, 
      embeddingModel: selectedModelName,
      embeddingApiUrl: apiUrl  // 自动设置
    }));
  }}
>
  {embeddingModels.map((model) => (
    <option key={model.modelName} value={model.modelName}>
      {model.modelName} ({model.provider})
    </option>
  ))}
</select>
{vectorDbSettings.embeddingApiUrl && (
  <p className="text-xs text-gray-500 mt-1">
    API: {vectorDbSettings.embeddingApiUrl}
  </p>
)}
```

#### 更新 API 调用

```typescript
// frotend/src/services/api.ts

updateSettings: async (settings: {
  vectorDbType?: string;
  embeddingModel?: string;
  embeddingApiUrl?: string;  // 新增
  embeddingDimension?: number;
  chunkSize?: number;
  chunkOverlap?: number;
  connectionString?: string;
  similarityThreshold?: number;
  maxSearchResults?: number;
}) => {
  const payload = {
    vectorDbType: (settings as any).vectorDbType ?? (settings as any).type ?? 'pgvector',
    embeddingModel: settings.embeddingModel,
    embeddingApiUrl: settings.embeddingApiUrl,  // 新增
    embeddingDimension: settings.embeddingDimension,
    // ... 其他字段 ...
  };
  // ...
}
```

### 4. 数据库迁移

#### PostgreSQL 迁移脚本

```sql
-- backend/migrations/003_add_embedding_api_url.sql

ALTER TABLE knowledge_base_settings 
ADD COLUMN IF NOT EXISTS embedding_api_url VARCHAR(500);

COMMENT ON COLUMN knowledge_base_settings.embedding_api_url IS '嵌入模型 API 地址';

-- 更新现有记录
UPDATE knowledge_base_settings ks
SET embedding_api_url = mc.api_endpoint || '/api/embeddings'
FROM model_configs mc
WHERE ks.embedding_model = mc.model_name
  AND mc.type = 'embedding'
  AND mc.api_endpoint IS NOT NULL
  AND (ks.embedding_api_url IS NULL OR ks.embedding_api_url = '');
```

#### SQLite 迁移脚本

```python
# backend/scripts/add_embedding_api_url.py

python backend/scripts/add_embedding_api_url.py
```

## 工作流程

### 用户选择嵌入模型时

1. 用户在"知识库设置"中选择嵌入模型
2. 前端自动从模型列表中查找该模型的 `apiEndpoint`
3. 自动设置 `embeddingApiUrl` 字段
4. 在界面上显示 API URL（如果有）
5. 用户点击"保存"
6. 前端将 `embeddingModel` 和 `embeddingApiUrl` 一起发送到后端
7. 后端保存到数据库

### 测试嵌入模型时

1. 用户点击"测试嵌入模型连接"
2. 前端发送当前选中的 `embeddingModel`（可选：`embeddingApiUrl`）
3. 后端按以下优先级获取 API URL：
   - 请求参数中的 `embeddingApiUrl`
   - 数据库设置中的 `embedding_api_url`
   - 模型配置表中的 `api_endpoint`
   - 环境变量 `EMBEDDINGS_API_URL`
4. 使用获取到的 API URL 测试连接
5. 返回测试结果（成功/失败、维度、API 风格等）

### 向量化文档时

1. 系统从设置中读取 `embedding_model` 和 `embedding_api_url`
2. 如果 `embedding_api_url` 为空，尝试从模型配置中获取
3. 使用获取到的 API URL 调用嵌入服务
4. 生成向量并存储到数据库

## 模型管理 API 返回数据示例

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
        "apiKey": "",
        "apiEndpoint": "http://20e5af39.r30.cpolar.top",
        "temperature": 0.7,
        "maxTokens": 2048,
        "topP": null,
        "systemPrompt": "",
        "status": "active",
        "isDefault": false,
        "createdAt": "2025-11-11T06:42:40.679390",
        "updatedAt": "2025-11-12T06:07:43.622236",
        "description": "嵌入模型"
      }
    ]
  }
}
```

## 测试步骤

1. **运行数据库迁移**
   ```bash
   python backend/scripts/add_embedding_api_url.py
   ```

2. **重启后端服务**
   ```bash
   cd backend
   python run.py
   ```

3. **测试模型选择**
   - 打开知识库设置页面
   - 选择一个嵌入模型
   - 确认下方显示了 API URL
   - 点击"保存"

4. **测试嵌入模型连接**
   - 点击"测试嵌入模型连接"按钮
   - 应该连接到模型配置中的 API 端点
   - 查看测试结果

5. **验证数据库**
   ```sql
   SELECT id, embedding_model, embedding_api_url FROM knowledge_base_settings;
   ```

## 优势

1. **自动化**：选择模型时自动获取 API 端点，无需手动配置
2. **灵活性**：支持从多个来源获取 API URL（请求参数、数据库、模型配置、环境变量）
3. **用户友好**：界面上显示当前使用的 API URL，便于确认
4. **向后兼容**：如果模型配置中没有 API 端点，仍然可以使用环境变量
5. **集中管理**：所有模型配置在"模型管理"页面统一管理

## 相关文件

- `backend/models/settings.py` - 设置数据模型
- `backend/routes/settings.py` - 设置管理路由
- `backend/migrations/003_add_embedding_api_url.sql` - PostgreSQL 迁移脚本
- `backend/scripts/add_embedding_api_url.py` - SQLite 迁移脚本
- `frotend/src/pages/KnowledgeBase.tsx` - 知识库设置页面
- `frotend/src/services/api.ts` - API 调用封装

## 注意事项

1. **URL 格式**：系统会自动确保 API URL 包含 `/api/embeddings` 路径
2. **优先级**：如果用户手动设置了 `embeddingApiUrl`，将优先使用用户设置的值
3. **回退机制**：如果所有来源都没有 API URL，将使用环境变量中的默认值
4. **模型配置**：确保在"模型管理"中正确配置了嵌入模型的 API 端点
