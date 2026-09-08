import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useModel } from '@/contexts/modelContext';
import { ModelConfig, ModelProvider, ModelStatus, ModelType } from '@/types/model';
import Navbar from '@/components/Navbar';
import Sidebar from '@/components/Sidebar';
import { toast } from 'sonner';

export default function ModelManager() {
  const { models, loading, addModel, updateModel, deleteModel, testModel, setDefaultModel, getProviderConfig } = useModel();
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingModel, setEditingModel] = useState<ModelConfig | null>(null);
  const [filterType, setFilterType] = useState<ModelType | 'all'>('all');  // 添加模型类型筛选
  const [formData, setFormData] = useState({
    name: '',
    provider: ModelProvider.OPENAI,
    type: ModelType.CHAT,  // 添加模型类型字段
    modelName: '',
    apiKey: '',
    apiEndpoint: '',
    temperature: 0.7,
    maxTokens: 2048,
    systemPrompt: '',
    description: '',
    isDefault: false
  });

  // 重置表单
  const resetForm = () => {
    setFormData({
      name: '',
      provider: ModelProvider.OPENAI,
      type: ModelType.CHAT,  // 添加模型类型字段
      modelName: '',
      apiKey: '',
      apiEndpoint: '',
      temperature: 0.7,
      maxTokens: 2048,
      systemPrompt: '',
      description: '',
      isDefault: false
    });
    setEditingModel(null);
  };

  // 打开添加模型模态框
  const handleAddModel = () => {
    resetForm();
    setShowAddModal(true);
  };

  // 打开编辑模型模态框
  const handleEditModel = (model: ModelConfig) => {
    setFormData({
      name: model.name,
      provider: model.provider,
      type: model.type,  // 添加模型类型字段
      modelName: model.modelName,
      apiKey: model.apiKey || '',
      apiEndpoint: model.apiEndpoint || '',
      temperature: model.temperature || 0.7,
      maxTokens: model.maxTokens || 2048,
      systemPrompt: model.systemPrompt || '',
      description: model.description || '',
      isDefault: model.isDefault
    });
    setEditingModel(model);
    setShowAddModal(true);
  };

  // 提交表单
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!formData.name || !formData.modelName) {
      toast.error('请填写模型名称和模型ID');
      return;
    }

    const providerConfig = getProviderConfig(formData.provider);
    
    // 检查必填字段
    for (const field of providerConfig.requiredFields) {
      if (!formData[field as keyof typeof formData]) {
        toast.error(`请填写必填字段: ${field}`);
        return;
      }
    }

    try {
      if (editingModel) {
        await updateModel(editingModel.id, formData);
      } else {
        await addModel({
          ...formData,
          status: ModelStatus.INACTIVE
        });
      }
      setShowAddModal(false);
      resetForm();
    } catch (error) {
      console.error('保存模型失败:', error);
    }
  };

  // 删除模型
  const handleDeleteModel = async (id: string) => {
    if (window.confirm('确定要删除这个模型吗？')) {
      await deleteModel(id);
    }
  };

  // 测试模型
  const handleTestModel = async (id: string) => {
    await testModel(id);
  };

  // 设置默认模型
  const handleSetDefault = async (id: string) => {
    await setDefaultModel(id);
  };

  // 获取状态颜色
  const getStatusColor = (status: ModelStatus) => {
    switch (status) {
      case ModelStatus.ACTIVE:
        return 'bg-green-100 text-green-800';
      case ModelStatus.INACTIVE:
        return 'bg-gray-100 text-gray-800';
      case ModelStatus.ERROR:
        return 'bg-red-100 text-red-800';
      case ModelStatus.TESTING:
        return 'bg-blue-100 text-blue-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  // 获取状态文本
  const getStatusText = (status: ModelStatus) => {
    switch (status) {
      case ModelStatus.ACTIVE:
        return '活跃';
      case ModelStatus.INACTIVE:
        return '未激活';
      case ModelStatus.ERROR:
        return '错误';
      case ModelStatus.TESTING:
        return '测试中';
      default:
        return '未知';
    }
  };

  return (
    <div className="bg-gradient-to-br from-blue-50 via-white to-purple-50 min-h-screen flex flex-col">
      <Navbar />
      <div className="flex flex-1">
        <Sidebar />
        <main className="flex-1 ml-64 p-6">
          <div className="max-w-7xl mx-auto">
            <motion.header 
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="mb-6"
            >
              <div className="bg-white rounded-2xl shadow-lg p-6 backdrop-blur-lg bg-opacity-90">
                <div className="flex justify-between items-center">
                  <div className="flex items-center space-x-4">
                    <div className="p-3 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl shadow-lg">
                      <i className="fas fa-robot text-white text-2xl"></i>
                    </div>
                    <div>
                      <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">模型管理</h1>
                      <p className="text-gray-600 mt-1">配置和管理AI模型</p>
                    </div>
                  </div>
                  <motion.button
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    onClick={handleAddModel}
                    className="px-4 py-2 bg-blue-600 text-white rounded-xl font-medium hover:bg-blue-700 transition-all flex items-center shadow-md"
                  >
                    <i className="fas fa-plus mr-2"></i>
                    添加模型
                  </motion.button>
                </div>
              </div>
            </motion.header>

            {/* 模型类型筛选器 */}
            <motion.div 
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.1 }}
              className="mb-6"
            >
              <div className="bg-white rounded-xl shadow-sm p-4">
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => setFilterType('all')}
                    className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                      filterType === 'all'
                        ? 'bg-blue-600 text-white'
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    全部模型
                  </button>
                  <button
                    onClick={() => setFilterType(ModelType.CHAT)}
                    className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                      filterType === ModelType.CHAT
                        ? 'bg-purple-600 text-white'
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    对话模型
                  </button>
                  <button
                    onClick={() => setFilterType(ModelType.EMBEDDING)}
                    className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                      filterType === ModelType.EMBEDDING
                        ? 'bg-green-600 text-white'
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    向量模型
                  </button>
                </div>
              </div>
            </motion.div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
              {models
                .filter(model => {
                  // 确保类型比较正确，使用字符串比较
                  return filterType === 'all' || String(model.type) === String(filterType);
                })
                .map((model) => {
                const providerConfig = getProviderConfig(model.provider);
                return (
                  <motion.div
                    key={model.id}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.3 }}
                    className="bg-white rounded-xl shadow-sm overflow-hidden border border-gray-100 hover:shadow-xl transition-all duration-300 hover:-translate-y-1 max-w-sm"
                  >
                    <div className={`h-1.5 bg-gradient-to-r from-${providerConfig.color}-400 to-${providerConfig.color}-600`}></div>
                    <div className="p-4">
                      <div className="flex justify-between items-start mb-3">
                        <div className="flex items-center space-x-3">
                          <div className={`w-10 h-10 bg-gradient-to-br from-${providerConfig.color}-100 to-${providerConfig.color}-200 rounded-lg flex items-center justify-center shadow-sm`}>
                            <i className={`fas ${providerConfig.icon} text-${providerConfig.color}-600`}></i>
                          </div>
                          <div>
                            <h3 className="text-sm font-bold text-gray-900 truncate max-w-[140px]">{model.name}</h3>
                            <p className="text-xs text-gray-500">{providerConfig.displayName}</p>
                          </div>
                        </div>
                        <div className="flex flex-col items-end space-y-1">
                          <div className="flex items-center space-x-1">
                            {model.isDefault && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 border border-blue-200">
                                <i className="fas fa-star mr-1 text-xs"></i>默认
                              </span>
                            )}
                            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${getStatusColor(model.status)}`}>
                              {getStatusText(model.status)}
                            </span>
                          </div>
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                            model.type === ModelType.CHAT 
                              ? 'bg-purple-100 text-purple-800 border border-purple-200' 
                              : 'bg-green-100 text-green-800 border border-green-200'
                          }`}>
                            {model.type === ModelType.CHAT ? '对话' : '向量'}
                          </span>
                        </div>
                      </div>
                      
                      <div className="bg-gray-50 rounded-lg p-3 mb-3 space-y-2">
                        <div className="flex justify-between text-xs">
                          <span className="text-gray-500 font-medium">模型:</span>
                          <span className="text-gray-900 font-mono truncate ml-2 max-w-[120px]" title={model.modelName}>{model.modelName}</span>
                        </div>
                        {model.apiEndpoint && (
                          <div className="flex justify-between text-xs">
                            <span className="text-gray-500 font-medium">端点:</span>
                            <span className="text-gray-900 font-mono truncate ml-2 max-w-[120px]" title={model.apiEndpoint}>{model.apiEndpoint}</span>
                          </div>
                        )}
                        {model.type === ModelType.CHAT && (
                          <div className="grid grid-cols-2 gap-x-2">
                            <div className="flex justify-between text-xs">
                              <span className="text-gray-500 font-medium">温度:</span>
                              <span className="text-gray-900 font-medium">{model.temperature}</span>
                            </div>
                            <div className="flex justify-between text-xs">
                              <span className="text-gray-500 font-medium">令牌:</span>
                              <span className="text-gray-900 font-medium">{model.maxTokens}</span>
                            </div>
                          </div>
                        )}
                      </div>
                      
                      {model.description && (
                        <p className="text-xs text-gray-600 mb-3 line-clamp-2 bg-blue-50 p-2 rounded-md">{model.description}</p>
                      )}
                      
                      <div className="flex justify-between items-center">
                        <div className="flex space-x-2">
                          <motion.button
                            whileHover={{ scale: 1.05 }}
                            whileTap={{ scale: 0.95 }}
                            onClick={() => handleEditModel(model)}
                            className="p-2 text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors"
                            title="编辑"
                          >
                            <i className="fas fa-edit text-sm"></i>
                          </motion.button>
                          <motion.button
                            whileHover={{ scale: 1.05 }}
                            whileTap={{ scale: 0.95 }}
                            onClick={() => handleTestModel(model.id)}
                            disabled={model.status === ModelStatus.TESTING}
                            className="p-2 text-green-600 bg-green-50 hover:bg-green-100 rounded-lg transition-colors disabled:opacity-50"
                            title="测试连接"
                          >
                            <i className="fas fa-plug text-sm"></i>
                          </motion.button>
                          {!model.isDefault && (
                            <motion.button
                              whileHover={{ scale: 1.05 }}
                              whileTap={{ scale: 0.95 }}
                              onClick={() => handleSetDefault(model.id)}
                              className="p-2 text-purple-600 bg-purple-50 hover:bg-purple-100 rounded-lg transition-colors"
                              title="设为默认"
                            >
                              <i className="fas fa-star text-sm"></i>
                            </motion.button>
                          )}
                        </div>
                        {!model.isDefault && (
                          <motion.button
                            whileHover={{ scale: 1.05 }}
                            whileTap={{ scale: 0.95 }}
                            onClick={() => handleDeleteModel(model.id)}
                            className="p-2 text-red-600 bg-red-50 hover:bg-red-100 rounded-lg transition-colors"
                            title="删除"
                          >
                            <i className="fas fa-trash text-sm"></i>
                          </motion.button>
                        )}
                      </div>
                    </div>
                  </motion.div>
                );
              })}
            </div>

            {models.length === 0 && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="bg-white rounded-xl shadow-md p-12 text-center"
              >
                <div className="w-20 h-20 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <i className="fas fa-robot text-gray-400 text-3xl"></i>
                </div>
                <h3 className="text-xl font-semibold text-gray-700 mb-2">暂无模型</h3>
                <p className="text-gray-500 mb-6">添加您的第一个AI模型开始使用</p>
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={handleAddModel}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-all"
                >
                  <i className="fas fa-plus mr-2"></i>
                  添加模型
                </motion.button>
              </motion.div>
            )}
          </div>
        </main>
      </div>

      {/* 添加/编辑模型模态框 */}
      {showAddModal && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4"
          onClick={() => setShowAddModal(false)}
        >
          <motion.div
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.9, opacity: 0 }}
            className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6 border-b border-gray-200">
              <h2 className="text-xl font-semibold text-gray-900">
                {editingModel ? '编辑模型' : '添加新模型'}
              </h2>
            </div>
            
            <form onSubmit={handleSubmit} className="p-6">
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">模型名称</label>
                  <input
                    type="text"
                    list="model-names"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    placeholder="选择或输入模型名称"
                    required
                  />
                  <datalist id="model-names">
                    {/* 对话模型 */}
                    <option value="gpt-4">GPT-4</option>
                    <option value="gpt-4-turbo">GPT-4 Turbo</option>
                    <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
                    <option value="claude-3-opus">Claude 3 Opus</option>
                    <option value="claude-3-sonnet">Claude 3 Sonnet</option>
                    <option value="claude-3-haiku">Claude 3 Haiku</option>
                    <option value="gemini-pro">Gemini Pro</option>
                    <option value="llama-3-70b">Llama 3 70B</option>
                    <option value="llama-3-8b">Llama 3 8B</option>
                    <option value="qwen-72b">Qwen 72B</option>
                    <option value="qwen-14b">Qwen 14B</option>
                    <option value="qwen-7b">Qwen 7B</option>
                    <option value="chatglm3-6b">ChatGLM3 6B</option>
                    <option value="baichuan2-13b">Baichuan2 13B</option>
                    
                    {/* 嵌入模型 */}
                    <option value="text-embedding-3-large">text-embedding-3-large</option>
                    <option value="text-embedding-3-small">text-embedding-3-small</option>
                    <option value="text-embedding-ada-002">text-embedding-ada-002</option>
                    <option value="bge-large-zh-v1.5">bge-large-zh-v1.5</option>
                    <option value="bge-base-zh-v1.5">bge-base-zh-v1.5</option>
                    <option value="bge-small-zh-v1.5">bge-small-zh-v1.5</option>
                    <option value="bge-m3:latest">bge-m3:latest</option>
                    <option value="nomic-embed-text">nomic-embed-text</option>
                    <option value="mxbai-embed-large">mxbai-embed-large</option>
                    <option value="all-minilm-l6-v2">all-minilm-l6-v2</option>
                    <option value="paraphrase-multilingual">paraphrase-multilingual</option>
                  </datalist>
                  <p className="text-xs text-gray-500 mt-1">可以从列表中选择或手动输入模型名称</p>
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">模型提供商</label>
                  <select
                    value={formData.provider}
                    onChange={(e) => setFormData({ ...formData, provider: e.target.value as ModelProvider })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  >
                    {Object.values(ModelProvider).map((provider) => {
                      const config = getProviderConfig(provider);
                      return (
                        <option key={provider} value={provider}>
                          {config.displayName}
                        </option>
                      );
                    })}
                  </select>
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">模型类型</label>
                  <select
                    value={formData.type}
                    onChange={(e) => setFormData({ ...formData, type: e.target.value as ModelType })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value={ModelType.CHAT}>对话模型</option>
                    <option value={ModelType.EMBEDDING}>向量模型</option>
                  </select>
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">模型ID</label>
                  <input
                    type="text"
                    value={formData.modelName}
                    onChange={(e) => setFormData({ ...formData, modelName: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    required
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    例如: gpt-4, llama2, qwen-turbo 等
                  </p>
                </div>
                
                {getProviderConfig(formData.provider).requiredFields.includes('apiKey') && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">API密钥</label>
                    <input
                      type="password"
                      value={formData.apiKey}
                      onChange={(e) => setFormData({ ...formData, apiKey: e.target.value })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      required={getProviderConfig(formData.provider).requiredFields.includes('apiKey')}
                    />
                  </div>
                )}
                
                {getProviderConfig(formData.provider).requiredFields.includes('apiEndpoint') && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">API端点</label>
                    <input
                      type="text"
                      value={formData.apiEndpoint}
                      onChange={(e) => setFormData({ ...formData, apiEndpoint: e.target.value })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      placeholder={formData.provider === ModelProvider.OLLAMA ? "例如: http://localhost:11434" : "例如: https://api.openai.com/v1"}
                      required={getProviderConfig(formData.provider).requiredFields.includes('apiEndpoint')}
                    />
                    <p className="text-xs text-gray-500 mt-1">
                      {formData.provider === ModelProvider.OLLAMA 
                        ? "Ollama本地服务端点，默认端口为11434" 
                        : "API端点URL，通常以/v1结尾"}
                    </p>
                  </div>
                )}
                
                {formData.type === ModelType.CHAT && (
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">温度</label>
                      <input
                        type="number"
                        step="0.1"
                        min="0"
                        max="2"
                        value={formData.temperature}
                        onChange={(e) => setFormData({ ...formData, temperature: parseFloat(e.target.value) })}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      />
                    </div>
                    
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">最大令牌数</label>
                      <input
                        type="number"
                        min="1"
                        value={formData.maxTokens}
                        onChange={(e) => setFormData({ ...formData, maxTokens: parseInt(e.target.value) })}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      />
                    </div>
                  </div>
                )}
                
                {formData.type === ModelType.CHAT && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">系统提示</label>
                    <textarea
                      value={formData.systemPrompt}
                      onChange={(e) => setFormData({ ...formData, systemPrompt: e.target.value })}
                      rows={3}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      placeholder="例如: 你是一个专业的医学助手..."
                    />
                  </div>
                )}
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">描述</label>
                  <textarea
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    rows={2}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    placeholder="模型用途描述..."
                  />
                </div>
                
                <div className="flex items-center">
                  <input
                    type="checkbox"
                    id="isDefault"
                    checked={formData.isDefault}
                    onChange={(e) => setFormData({ ...formData, isDefault: e.target.checked })}
                    className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                  />
                  <label htmlFor="isDefault" className="ml-2 block text-sm text-gray-700">
                    设为默认模型
                  </label>
                </div>
              </div>
              
              <div className="flex justify-end space-x-3 mt-6">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
                >
                  {loading ? '保存中...' : (editingModel ? '更新' : '添加')}
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </div>
  );
}