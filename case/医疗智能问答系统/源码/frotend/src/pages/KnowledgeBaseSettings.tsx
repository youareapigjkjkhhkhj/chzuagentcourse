import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import Navbar from '../components/Navbar';
import Sidebar from '../components/Sidebar';
import {
  FaCog,
  FaDatabase,
  FaCheckCircle,
  FaTimesCircle,
  FaSpinner,
  FaSave,
  FaUndo,
  FaVial
} from 'react-icons/fa';
import { kbSettingsAPI, modelAPI } from '../services/api';
import { ModelConfig, ModelType } from '../types/models';

interface KBSettings {
  vectorDbType: string;
  embeddingModel: string;
  embeddingDimension: number;
  chunkSize: number;
  chunkOverlap: number;
  similarityThreshold: number;
  maxSearchResults: number;
}

const KnowledgeBaseSettings: React.FC = () => {

  // 设置状态
  const [settings, setSettings] = useState<KBSettings>({
    vectorDbType: 'pgvector',
    embeddingModel: 'nomic-embed-text',
    embeddingDimension: 1536,
    chunkSize: 1000,
    chunkOverlap: 200,
    similarityThreshold: 0.7,
    maxSearchResults: 10
  });

  // 嵌入模型数据
  const [embeddingModels, setEmbeddingModels] = useState<ModelConfig[]>([]);

  const [originalSettings, setOriginalSettings] = useState<KBSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
    dimension?: number;
    apiStyle?: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // 加载设置
  useEffect(() => {
    loadSettings();
    loadEmbeddingModels();
  }, []);

  // 加载嵌入模型
  const loadEmbeddingModels = async () => {
    try {
      const response = await modelAPI.getModels();
      if (response.success && response.data?.models) {
        const allModels = response.data.models || [];
        const embeddingModelsList = allModels.filter((model: ModelConfig) => 
          model.type === ModelType.EMBEDDING
        );
        setEmbeddingModels(embeddingModelsList);
      }
    } catch (error) {
      console.error('加载嵌入模型失败:', error);
    }
  };

  const loadSettings = async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await kbSettingsAPI.getSettings();

      if (response.success && response.data?.settings) {
        const loadedSettings = {
          vectorDbType: response.data.settings.vectorDbType || 'pgvector',
          embeddingModel: response.data.settings.embeddingModel || 'nomic-embed-text',
          embeddingDimension: response.data.settings.embeddingDimension || 1536,
          chunkSize: response.data.settings.chunkSize || 1000,
          chunkOverlap: response.data.settings.chunkOverlap || 200,
          similarityThreshold: response.data.settings.similarityThreshold || 0.7,
          maxSearchResults: response.data.settings.maxSearchResults || 10
        };
        setSettings(loadedSettings);
        setOriginalSettings(loadedSettings);
      }
    } catch (error) {
      console.error('加载设置失败:', error);
      setError('加载设置失败，请刷新页面重试');
    } finally {
      setLoading(false);
    }
  };

  const handleSaveSettings = async () => {
    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      const response = await kbSettingsAPI.updateSettings(settings);

      if (response.success) {
        setSuccess('设置保存成功');
        setOriginalSettings(settings);
        setTimeout(() => setSuccess(null), 3000);
      }
    } catch (error) {
      console.error('保存设置失败:', error);
      setError('保存设置失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  const handleTestEmbedding = async () => {
    try {
      setTesting(true);
      setTestResult(null);
      setError(null);

      const response = await kbSettingsAPI.testEmbedding({
        embeddingModel: settings.embeddingModel
      });

      if (response.success && response.data) {
        setTestResult({
          success: response.data.available || false,
          message: response.data.message || '测试完成',
          dimension: response.data.dimension,
          apiStyle: response.data.apiStyle
        });
      }
    } catch (error) {
      console.error('测试嵌入模型失败:', error);
      setTestResult({
        success: false,
        message: '测试失败，请检查配置'
      });
    } finally {
      setTesting(false);
    }
  };

  const handleResetSettings = () => {
    if (originalSettings) {
      setSettings(originalSettings);
      setTestResult(null);
      setError(null);
      setSuccess(null);
    }
  };

  const hasChanges = () => {
    if (!originalSettings) return false;
    return JSON.stringify(settings) !== JSON.stringify(originalSettings);
  };

  return (
    <div className="bg-gray-50 min-h-screen flex flex-col">
      <Navbar />
      <div className="flex flex-1">
        <Sidebar />
        <main className="flex-1 ml-64 p-6">
          <div className="max-w-4xl mx-auto">
            {/* 页面标题 */}
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center">
                <FaCog className="text-blue-600 text-2xl mr-3" />
                <div>
                  <h1 className="text-2xl font-bold text-gray-900">知识库设置</h1>
                  <p className="text-sm text-gray-600 mt-1">配置向量数据库和嵌入模型参数</p>
                </div>
              </div>
            </div>

            {/* 成功提示 */}
            {success && (
              <motion.div
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                className="mb-6 p-4 bg-green-50 border border-green-200 rounded-lg flex items-center"
              >
                <FaCheckCircle className="text-green-500 mr-3" />
                <span className="text-green-800">{success}</span>
              </motion.div>
            )}

            {/* 错误提示 */}
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg flex items-center"
              >
                <FaTimesCircle className="text-red-500 mr-3" />
                <span className="text-red-800">{error}</span>
              </motion.div>
            )}

            {loading ? (
              <div className="flex justify-center items-center py-12">
                <FaSpinner className="animate-spin text-blue-600 text-2xl mr-3" />
                <span className="text-gray-600">加载中...</span>
              </div>
            ) : (
              <>
                {/* 向量数据库设置 */}
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="bg-white rounded-lg shadow-sm p-6 mb-6"
                >
                  <div className="flex items-center mb-4">
                    <FaDatabase className="text-blue-600 mr-2" />
                    <h2 className="text-lg font-semibold text-gray-900">向量数据库</h2>
                  </div>

                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        数据库类型
                      </label>
                      <input
                        type="text"
                        value={settings.vectorDbType}
                        disabled
                        className="w-full px-4 py-2 border border-gray-300 rounded-lg bg-gray-50 text-gray-600 cursor-not-allowed"
                      />
                      <p className="text-xs text-gray-500 mt-1">
                        使用 PostgreSQL + pgvector 扩展
                      </p>
                    </div>
                  </div>
                </motion.div>

                {/* 嵌入模型设置 */}
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.1 }}
                  className="bg-white rounded-lg shadow-sm p-6 mb-6"
                >
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-gray-900">嵌入模型</h2>
                    <motion.button
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                      onClick={handleTestEmbedding}
                      disabled={testing}
                      className="flex items-center px-3 py-1 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50 text-sm"
                    >
                      {testing ? (
                        <>
                          <FaSpinner className="animate-spin mr-2" />
                          测试中
                        </>
                      ) : (
                        <>
                          <FaVial className="mr-2" />
                          测试连接
                        </>
                      )}
                    </motion.button>
                  </div>

                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        模型名称
                      </label>
                      <select
                        value={settings.embeddingModel}
                        onChange={(e) => setSettings({ ...settings, embeddingModel: e.target.value })}
                        className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      >
                        {embeddingModels.length === 0 ? (
                          <option value="">请先在"模型管理"中添加向量模型</option>
                        ) : (
                          embeddingModels.map((model) => (
                            <option key={model.id} value={model.modelName}>
                              {model.modelName} ({model.provider})
                            </option>
                          ))
                        )}
                      </select>
                      <p className="text-xs text-gray-500 mt-1">
                        支持 Ollama 或 OpenAI 兼容的嵌入模型
                        {embeddingModels.length > 0 && ` (共 ${embeddingModels.length} 个可用模型)`}
                      </p>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        向量维度
                      </label>
                      <input
                        type="number"
                        value={settings.embeddingDimension}
                        onChange={(e) => setSettings({ ...settings, embeddingDimension: parseInt(e.target.value) })}
                        className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                        min="1"
                      />
                      <p className="text-xs text-gray-500 mt-1">
                        向量的维度，需要与模型输出维度匹配
                      </p>
                    </div>

                    {/* 测试结果 */}
                    {testResult && (
                      <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className={`p-4 rounded-lg border ${
                          testResult.success
                            ? 'bg-green-50 border-green-200'
                            : 'bg-red-50 border-red-200'
                        }`}
                      >
                        <div className="flex items-start">
                          {testResult.success ? (
                            <FaCheckCircle className="text-green-500 mr-3 mt-0.5" />
                          ) : (
                            <FaTimesCircle className="text-red-500 mr-3 mt-0.5" />
                          )}
                          <div className="flex-1">
                            <p className={`font-medium ${
                              testResult.success ? 'text-green-800' : 'text-red-800'
                            }`}>
                              {testResult.message}
                            </p>
                            {testResult.success && testResult.dimension && (
                              <p className="text-sm text-green-700 mt-1">
                                检测到向量维度: {testResult.dimension}
                                {testResult.apiStyle && ` (${testResult.apiStyle} API)`}
                              </p>
                            )}
                          </div>
                        </div>
                      </motion.div>
                    )}
                  </div>
                </motion.div>

                {/* 文本处理设置 */}
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.2 }}
                  className="bg-white rounded-lg shadow-sm p-6 mb-6"
                >
                  <h2 className="text-lg font-semibold text-gray-900 mb-4">文本处理</h2>

                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        文本块大小 (Chunk Size)
                      </label>
                      <input
                        type="number"
                        value={settings.chunkSize}
                        onChange={(e) => setSettings({ ...settings, chunkSize: parseInt(e.target.value) })}
                        className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                        min="100"
                        max="5000"
                      />
                      <p className="text-xs text-gray-500 mt-1">
                        将长文档分割为多个文本块的大小（字符数）
                      </p>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        文本块重叠 (Chunk Overlap)
                      </label>
                      <input
                        type="number"
                        value={settings.chunkOverlap}
                        onChange={(e) => setSettings({ ...settings, chunkOverlap: parseInt(e.target.value) })}
                        className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                        min="0"
                        max="1000"
                      />
                      <p className="text-xs text-gray-500 mt-1">
                        相邻文本块之间的重叠字符数，用于保持上下文连贯性
                      </p>
                    </div>
                  </div>
                </motion.div>

                {/* 搜索设置 */}
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.3 }}
                  className="bg-white rounded-lg shadow-sm p-6 mb-6"
                >
                  <h2 className="text-lg font-semibold text-gray-900 mb-4">搜索设置</h2>

                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        相似度阈值
                      </label>
                      <div className="flex items-center gap-4">
                        <input
                          type="range"
                          value={settings.similarityThreshold}
                          onChange={(e) => setSettings({ ...settings, similarityThreshold: parseFloat(e.target.value) })}
                          className="flex-1"
                          min="0"
                          max="1"
                          step="0.05"
                        />
                        <span className="text-sm font-medium text-gray-900 w-12 text-right">
                          {settings.similarityThreshold.toFixed(2)}
                        </span>
                      </div>
                      <p className="text-xs text-gray-500 mt-1">
                        向量搜索的最低相似度要求（0-1之间）
                      </p>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        最大搜索结果数
                      </label>
                      <input
                        type="number"
                        value={settings.maxSearchResults}
                        onChange={(e) => setSettings({ ...settings, maxSearchResults: parseInt(e.target.value) })}
                        className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                        min="1"
                        max="100"
                      />
                      <p className="text-xs text-gray-500 mt-1">
                        单次搜索返回的最大结果数量
                      </p>
                    </div>
                  </div>
                </motion.div>

                {/* 操作按钮 */}
                <div className="flex justify-end gap-3">
                  <motion.button
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    onClick={handleResetSettings}
                    disabled={!hasChanges() || saving}
                    className="flex items-center px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <FaUndo className="mr-2" />
                    重置
                  </motion.button>
                  <motion.button
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    onClick={handleSaveSettings}
                    disabled={!hasChanges() || saving}
                    className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {saving ? (
                      <>
                        <FaSpinner className="animate-spin mr-2" />
                        保存中
                      </>
                    ) : (
                      <>
                        <FaSave className="mr-2" />
                        保存设置
                      </>
                    )}
                  </motion.button>
                </div>
              </>
            )}
          </div>
        </main>
      </div>
    </div>
  );
};

export default KnowledgeBaseSettings;
