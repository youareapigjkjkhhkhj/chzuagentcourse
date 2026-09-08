# 知识库设置界面说明

## 界面布局

### 配置向量数据库和嵌入模型参数

#### 1. 向量数据库类型
- **类型**: 只读下拉框
- **值**: PostgreSQL + pgvector 扩展
- **说明**: 系统现在使用 pgvector 作为向量数据库

#### 2. 嵌入模型
- **类型**: 文本输入框（带下拉提示）
- **功能**: 
  - 可以从列表中选择模型管理中的向量模型
  - 也可以手动输入自定义模型名称
- **支持**: Ollama 或 OpenAI 兼容的嵌入模型
- **自动功能**: 选择模型时自动填充 API URL

#### 3. 向量维度
- **类型**: 数字输入框
- **范围**: 128 - 4096
- **默认值**: 1536
- **说明**: 向量的维度，需要与模型输出维度匹配
- **常用值**:
  - text-embedding-3-small: 1536
  - text-embedding-3-large: 3072
  - bge-m3: 1024
  - nomic-embed-text: 768

#### 4. 文本块大小
- **类型**: 数字输入框
- **范围**: 100 - 4000
- **默认值**: 1000
- **说明**: 每个文本块的字符数

#### 5. 文本块重叠大小
- **类型**: 数字输入框
- **范围**: 0 - 1000
- **默认值**: 200
- **说明**: 相邻文本块的重叠字符数

#### 6. 数据库连接字符串
- **类型**: 只读文本框
- **说明**: pgvector 使用与主数据库相同的连接（由后端配置）

#### 7. 嵌入模型测试
- **类型**: 按钮
- **功能**: 测试所选嵌入模型是否可用
- **显示**: 测试结果（成功/失败、维度、API 风格）

## 使用流程

### 方式一：从模型管理中选择（推荐）

1. **在模型管理中添加向量模型**
   ```
   进入"模型管理"页面
   点击"添加模型"
   填写：
   - 模型名称: bge-m3:latest
   - 提供商: ollama
   - 类型: embedding
   - API 端点: http://your-server.com
   ```

2. **在知识库设置中选择**
   ```
   进入"知识库设置"
   在"嵌入模型"输入框中：
   - 点击输入框，会显示可用模型列表
   - 选择刚添加的模型
   - 系统自动填充 API URL
   ```

3. **设置向量维度**
   ```
   根据模型输出维度设置：
   - bge-m3:latest → 1024
   - text-embedding-3-small → 1536
   - nomic-embed-text → 768
   ```

4. **测试和保存**
   ```
   点击"测试嵌入模型连接"
   确认测试成功
   点击"保存"
   ```

### 方式二：手动输入模型名称

1. **直接输入模型名称**
   ```
   在"嵌入模型"输入框中输入：bge-m3:latest
   ```

2. **手动填写 API URL**（如果需要）
   ```
   系统会尝试从模型管理中查找
   如果找不到，需要确保 .env 中配置了 EMBEDDINGS_API_URL
   ```

3. **设置向量维度**
   ```
   输入对应的维度值
   ```

4. **保存设置**

## 界面示例

### 完整配置示例

```
┌─────────────────────────────────────────────────────────┐
│ 知识库设置                                               │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ 向量数据库类型                                           │
│ ┌─────────────────────────────────────────────────┐    │
│ │ pgvector (PostgreSQL)                      [▼] │    │
│ └─────────────────────────────────────────────────┘    │
│ 系统现在使用 pgvector 作为向量数据库                    │
│                                                          │
│ 嵌入模型                                                 │
│ ┌─────────────────────────────────────────────────┐    │
│ │ bge-m3:latest                              [▼] │    │
│ └─────────────────────────────────────────────────┘    │
│ 支持 Ollama 或 OpenAI 兼容的嵌入模型 (可从 3 个模型中选择) │
│ API: http://your-server.com/api/embeddings             │
│                                                          │
│ 向量维度                                                 │
│ ┌─────────────────────────────────────────────────┐    │
│ │ 1024                                            │    │
│ └─────────────────────────────────────────────────┘    │
│ 向量的维度，需要与模型输出维度匹配                       │
│                                                          │
│ 文本块大小                    文本块重叠大小             │
│ ┌──────────────────┐         ┌──────────────────┐      │
│ │ 1000             │         │ 200              │      │
│ └──────────────────┘         └──────────────────┘      │
│                                                          │
│ 数据库连接字符串                                         │
│ ┌─────────────────────────────────────────────────┐    │
│ │ postgresql://user:pass@host:5432/db             │    │
│ └─────────────────────────────────────────────────┘    │
│ pgvector 使用与主数据库相同的连接（由后端配置）          │
│                                                          │
│ 嵌入模型测试                                             │
│ ┌─────────────────────────────────────────────────┐    │
│ │          🔌 测试嵌入模型连接                    │    │
│ └─────────────────────────────────────────────────┘    │
│ 测试所选嵌入模型是否可用                                 │
│                                                          │
│                                    ┌────────┐ ┌────────┐│
│                                    │ 取消   │ │ 保存   ││
│                                    └────────┘ └────────┘│
└─────────────────────────────────────────────────────────┘
```

## 数据结构

### VectorDbSettings 接口

```typescript
interface VectorDbSettings {
  type: VectorDbType;              // 'pgvector'
  embeddingModel: string;          // 'bge-m3:latest'
  embeddingApiUrl?: string;        // 'http://server.com/api/embeddings'
  embeddingDimension?: number;     // 1024
  chunkSize: number;               // 1000
  chunkOverlap: number;            // 200
  connectionString: string;        // 数据库连接字符串
}
```

### 后端 API

```python
# backend/models/settings.py
class KnowledgeBaseSettings(db.Model):
    vector_db_type = db.Column(db.String(50), default='pgvector')
    embedding_model = db.Column(db.String(100))
    embedding_api_url = db.Column(db.String(500))
    embedding_dimension = db.Column(db.Integer, default=1536)
    chunk_size = db.Column(db.Integer, default=1000)
    chunk_overlap = db.Column(db.Integer, default=200)
    connection_string = db.Column(db.String(500))
```

## 常见模型维度

| 模型名称 | 提供商 | 维度 | 说明 |
|---------|--------|------|------|
| text-embedding-3-small | OpenAI | 1536 | OpenAI 小型嵌入模型 |
| text-embedding-3-large | OpenAI | 3072 | OpenAI 大型嵌入模型 |
| text-embedding-ada-002 | OpenAI | 1536 | OpenAI 旧版嵌入模型 |
| bge-large-zh-v1.5 | BAAI | 1024 | BGE 大型中文模型 |
| bge-base-zh-v1.5 | BAAI | 768 | BGE 基础中文模型 |
| bge-small-zh-v1.5 | BAAI | 512 | BGE 小型中文模型 |
| bge-m3:latest | BAAI | 1024 | BGE M3 多语言模型 |
| nomic-embed-text | Nomic | 768 | Nomic 文本嵌入模型 |
| mxbai-embed-large | MixedBread | 1024 | MixedBread 大型模型 |
| all-minilm-l6-v2 | Sentence Transformers | 384 | 轻量级嵌入模型 |

## 注意事项

1. **向量维度必须匹配**
   - 设置的维度必须与模型实际输出维度一致
   - 维度不匹配会导致向量化失败

2. **模型名称格式**
   - Ollama 模型：`model-name:tag`（如 `bge-m3:latest`）
   - OpenAI 模型：`model-name`（如 `text-embedding-3-small`）

3. **API URL 格式**
   - Ollama：`http://host:11434/api/embeddings`
   - OpenAI：`https://api.openai.com/v1/embeddings`
   - 自定义：确保端点兼容 OpenAI API 格式

4. **文本块设置**
   - 块大小太小：可能丢失上下文
   - 块大小太大：可能超过模型限制
   - 重叠太小：可能丢失跨块信息
   - 重叠太大：增加存储和计算成本

## 相关文件

- `frotend/src/pages/KnowledgeBase.tsx` - 知识库设置界面
- `backend/routes/settings.py` - 设置管理 API
- `backend/models/settings.py` - 设置数据模型
- `backend/utils/vector_manager.py` - 向量管理器
