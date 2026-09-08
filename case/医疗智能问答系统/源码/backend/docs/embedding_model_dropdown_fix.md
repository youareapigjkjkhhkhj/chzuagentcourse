# 嵌入模型下拉框说明

## 问题

用户反馈"知识库设置"页面中的嵌入模型没有下拉框。

## 实际情况

下拉框是存在的，但可能因为以下原因看起来"没有"：

1. **模型列表为空**：模型管理中没有添加 `type=embedding` 的向量模型
2. **只有一个选项**：只有默认模型（来自 .env）
3. **加载失败**：API 请求失败，没有加载到模型数据

## 解决方案

### 1. 添加了更好的用户提示

现在下拉框会显示：

- **有模型时**：显示所有向量模型，格式为 `模型名称 (提供商)`
- **无模型时**：显示提示 "请先在'模型管理'中添加向量模型"
- **警告消息**：如果没有模型，显示橙色警告文字
- **模型数量**：显示 "共 X 个可用的向量模型"

### 2. 添加了调试日志

在浏览器控制台可以看到：
```javascript
[KB] loadInitialData: loaded embedding models 1
[KB] embeddingModel changed: bge-m3:latest {modelName: "bge-m3:latest", ...}
```

## 使用步骤

### 步骤 1：在模型管理中添加向量模型

1. 进入"模型管理"页面
2. 点击"添加模型"按钮
3. 填写信息：
   ```
   模型名称: bge-m3:latest
   模型提供商: ollama
   模型类型: embedding (向量模型)
   API 端点: http://your-server.com
   状态: active
   ```
4. 点击"保存"

### 步骤 2：在知识库设置中选择模型

1. 进入"知识库"页面
2. 点击右上角的"设置"按钮
3. 在"嵌入模型"下拉框中：
   - 如果有模型：选择刚添加的模型
   - 如果没有模型：会显示提示信息
4. 系统会自动填充 API URL
5. 点击"保存"

### 步骤 3：测试模型

1. 点击"测试嵌入模型连接"按钮
2. 查看测试结果
3. 确认模型可用

## 下拉框代码

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
      if (!apiUrl.endsWith('/api/embeddings')) {
        apiUrl = `${apiUrl}/api/embeddings`;
      }
    }
    
    setVectorDbSettings(prev => ({ 
      ...prev, 
      embeddingModel: selectedModelName,
      embeddingApiUrl: apiUrl
    }));
  }}
  className="block w-full px-3 py-2 border border-gray-300 rounded-lg"
>
  {embeddingModels.length === 0 ? (
    <option value="">请先在"模型管理"中添加向量模型</option>
  ) : (
    embeddingModels.map((model) => (
      <option key={model.modelName} value={model.modelName}>
        {model.modelName} ({model.provider})
      </option>
    ))
  )}
</select>
```

## 数据流程

### 加载模型列表

```typescript
// 1. 从 API 获取所有模型
const modelsResponse = await modelAPI.getModels();

// 2. 过滤出向量模型
const embeddingModelsList = allModels.filter(
  model => model.type === ModelType.EMBEDDING
);

// 3. 如果当前保存的模型不在列表中，添加它（.env 默认模型）
if (savedModel && !embeddingModelsList.some(m => m.modelName === savedModel)) {
  embeddingModelsList.unshift({
    modelName: savedModel,
    provider: 'default (.env)',
    type: ModelType.EMBEDDING,
    apiEndpoint: settings.embeddingApiUrl || ''
  });
}

// 4. 设置到状态
setEmbeddingModels(embeddingModelsList);
```

### 选择模型

```typescript
// 1. 用户选择模型
onChange={(e) => {
  const selectedModelName = e.target.value;
  const selectedModel = embeddingModels.find(m => m.modelName === selectedModelName);
  
  // 2. 自动获取 API URL
  let apiUrl = '';
  if (selectedModel && selectedModel.apiEndpoint) {
    apiUrl = selectedModel.apiEndpoint;
    if (!apiUrl.endsWith('/api/embeddings')) {
      apiUrl = `${apiUrl}/api/embeddings`;
    }
  }
  
  // 3. 更新设置
  setVectorDbSettings({
    ...prev,
    embeddingModel: selectedModelName,
    embeddingApiUrl: apiUrl
  });
}}
```

## 故障排查

### 问题 1：下拉框显示"请先在'模型管理'中添加向量模型"

**原因**：模型管理中没有 `type=embedding` 的模型

**解决方案**：
1. 进入"模型管理"页面
2. 添加至少一个 `type=embedding` 的模型
3. 刷新"知识库设置"页面

### 问题 2：下拉框只有一个选项（默认模型）

**原因**：只有 .env 中的默认模型，模型管理中没有其他向量模型

**解决方案**：
1. 在"模型管理"中添加更多向量模型
2. 或者继续使用默认模型

### 问题 3：选择模型后 API URL 为空

**原因**：模型配置中没有设置 API 端点

**解决方案**：
1. 进入"模型管理"页面
2. 编辑该模型
3. 填写"API 端点"字段
4. 保存

### 问题 4：下拉框不显示

**原因**：可能是 CSS 或 JavaScript 错误

**检查步骤**：
1. 打开浏览器开发者工具（F12）
2. 查看 Console 标签页是否有错误
3. 查看 Network 标签页，确认 API 请求成功
4. 在 Console 中输入：`console.log(embeddingModels)` 查看模型列表

## 界面截图说明

### 有模型时

```
嵌入模型
┌─────────────────────────────────────┐
│ bge-m3:latest (ollama)         ▼   │
├─────────────────────────────────────┤
│ bge-m3:latest (ollama)              │
│ text-embedding-3-small (openai)     │
│ nomic-embed-text (ollama)           │
└─────────────────────────────────────┘
API: http://your-server.com/api/embeddings
共 3 个可用的向量模型
```

### 无模型时

```
嵌入模型
┌─────────────────────────────────────┐
│ 请先在"模型管理"中添加向量模型  ▼  │
└─────────────────────────────────────┘
⚠️ 未找到向量模型，请在"模型管理"页面添加 type=embedding 的模型
```

## 相关文件

- `frotend/src/pages/KnowledgeBase.tsx` - 知识库设置页面
- `frotend/src/pages/ModelManager.tsx` - 模型管理页面
- `frotend/src/services/api.ts` - API 调用
- `backend/routes/models.py` - 模型管理 API
- `backend/models/model.py` - 模型数据模型

## 总结

下拉框是存在的，并且功能完整：
- ✅ 显示模型管理中的所有向量模型
- ✅ 自动获取模型的 API 端点
- ✅ 支持 .env 默认模型作为回退
- ✅ 提供清晰的用户提示
- ✅ 显示模型数量和 API URL

如果看不到下拉框或选项，请检查模型管理中是否有向量模型。
