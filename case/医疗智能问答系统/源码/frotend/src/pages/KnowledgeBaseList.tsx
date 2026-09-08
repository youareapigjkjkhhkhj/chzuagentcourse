import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import Navbar from '../components/Navbar';
import Sidebar from '../components/Sidebar';
import SearchModal from '../components/SearchModal';
import {
  FaFolder,
  FaPlus,
  FaSearch,
  FaEye,
  FaEdit,
  FaTrash,
  FaDatabase,
  FaFileAlt,
  FaCheckCircle,
  FaTimesCircle,
  FaSpinner,
  FaTimes,
  FaFilter,
  FaArchive
} from 'react-icons/fa';
import { knowledgeBaseAPI, modelAPI } from '../services/api';
import { ModelConfig, ModelType } from '../types/models';

// 知识库接口
interface KnowledgeBase {
  id: string;
  name: string;
  description: string;
  embeddingModel: string;
  status: 'active' | 'archived';
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  // 统计信息
  totalDocuments?: number;
  publishedDocuments?: number;
  totalVectors?: number;
}

const KnowledgeBaseList: React.FC = () => {
  const navigate = useNavigate();

  // 状态管理
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [filteredKnowledgeBases, setFilteredKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'archived'>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 分页状态
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const itemsPerPage = 12;

  // 模态框状态
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedKnowledgeBase, setSelectedKnowledgeBase] = useState<KnowledgeBase | null>(null);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [kbToDelete, setKbToDelete] = useState<KnowledgeBase | null>(null);
  const [isGlobalSearchOpen, setIsGlobalSearchOpen] = useState(false);

  // 表单数据
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    embeddingModel: '',
    status: 'active' as 'active' | 'archived'
  });

  // 嵌入模型状态
  const [embeddingModels, setEmbeddingModels] = useState<ModelConfig[]>([]);

  // 加载知识库列表
  useEffect(() => {
    loadKnowledgeBases();
    loadEmbeddingModels();
  }, [currentPage, statusFilter]);

  // 加载嵌入模型
  const loadEmbeddingModels = async () => {
    try {
      const response = await modelAPI.getModels();
      if (response.success && response.data) {
        const models = response.data.models || [];
        const embeddingModelsList = models.filter((model: ModelConfig) => 
          model.type === ModelType.EMBEDDING
        );
        setEmbeddingModels(embeddingModelsList);
      }
    } catch (error) {
      console.error('加载嵌入模型失败:', error);
    }
  };

  // 过滤知识库
  useEffect(() => {
    if (!searchTerm) {
      setFilteredKnowledgeBases(knowledgeBases);
      return;
    }

    const filtered = knowledgeBases.filter(kb =>
      kb.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      kb.description.toLowerCase().includes(searchTerm.toLowerCase())
    );
    setFilteredKnowledgeBases(filtered);
  }, [knowledgeBases, searchTerm]);

  const loadKnowledgeBases = async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await knowledgeBaseAPI.getKnowledgeBases({
        page: currentPage,
        per_page: itemsPerPage,
        status: statusFilter === 'all' ? undefined : statusFilter
      });

      if (response.success && response.data) {
        const kbs = response.data.knowledgeBases || [];
        setKnowledgeBases(kbs);
        setFilteredKnowledgeBases(kbs);

        if (response.data.pagination) {
          setTotalPages(response.data.pagination.pages);
          setTotalCount(response.data.pagination.total);
        }
      }
    } catch (error) {
      console.error('加载知识库列表失败:', error);
      setError('加载知识库列表失败，请刷新页面重试');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateKnowledgeBase = async () => {
    if (!formData.name.trim()) {
      setError('请输入知识库名称');
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const response = await knowledgeBaseAPI.createKnowledgeBase({
        name: formData.name,
        description: formData.description,
        embeddingModel: formData.embeddingModel,
        status: formData.status
      });

      if (response.success) {
        setIsCreateModalOpen(false);
        resetForm();
        await loadKnowledgeBases();
      }
    } catch (error) {
      console.error('创建知识库失败:', error);
      setError('创建知识库失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateKnowledgeBase = async () => {
    if (!selectedKnowledgeBase || !formData.name.trim()) {
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const response = await knowledgeBaseAPI.updateKnowledgeBase(
        selectedKnowledgeBase.id,
        {
          name: formData.name,
          description: formData.description,
          embeddingModel: formData.embeddingModel,
          status: formData.status
        }
      );

      if (response.success) {
        setIsEditModalOpen(false);
        setSelectedKnowledgeBase(null);
        resetForm();
        await loadKnowledgeBases();
      }
    } catch (error) {
      console.error('更新知识库失败:', error);
      setError('更新知识库失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  // 处理删除知识库
  const handleDeleteKnowledgeBase = async () => {
    if (!selectedKnowledgeBase) return;
    
    try {
      await knowledgeBaseAPI.deleteKnowledgeBase(selectedKnowledgeBase.id);
      toast.success('知识库删除成功');
      loadKnowledgeBases(); // 重新加载知识库列表
      closeDeleteModal();
    } catch (error: any) {
      console.error('删除知识库失败:', error);
      toast.error(error.message || '删除知识库失败');
    }
  };
  
  // 处理向量化知识库
  const handleVectorizeKnowledgeBase = async (id: string, name: string) => {
    if (window.confirm(`确定要向量化知识库 "${name}" 吗？此操作可能需要一些时间。`)) {
      try {
        toast.info('开始向量化知识库，请稍候...');
        const result = await knowledgeBaseAPI.vectorizeKnowledgeBase(id);
        const summary = result.data?.summary || {};
        const processedCount = summary.success || 0;
        const failedCount = summary.failed || 0;
        const skippedCount = summary.skipped || 0;
        
        let message = `知识库向量化成功！已处理 ${processedCount} 个文档`;
        if (failedCount > 0) {
          message += `，失败 ${failedCount} 个`;
        }
        if (skippedCount > 0) {
          message += `，跳过 ${skippedCount} 个`;
        }
        
        toast.success(message);
        loadKnowledgeBases(); // 重新加载知识库列表以更新向量数
      } catch (error: any) {
        console.error('向量化知识库失败:', error);
        toast.error(error.message || '向量化知识库失败');
      }
    }
  };

  const openEditModal = (kb: KnowledgeBase) => {
    setSelectedKnowledgeBase(kb);
    setFormData({
      name: kb.name,
      description: kb.description,
      embeddingModel: kb.embeddingModel,
      status: kb.status
    });
    setIsEditModalOpen(true);
  };

  const openDeleteModal = (kb: KnowledgeBase) => {
    setKbToDelete(kb);
    setIsDeleteModalOpen(true);
  };

  const resetForm = () => {
    setFormData({
      name: '',
      description: '',
      embeddingModel: '',
      status: 'active'
    });
  };

  const formatDate = (dateString: string) => {
    const options: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'long', day: 'numeric' };
    return new Date(dateString).toLocaleDateString('zh-CN', options);
  };

  const handleViewKnowledgeBase = (kbId: string) => {
    navigate(`/knowledge/${kbId}`);
  };

  return (
    <div className="bg-gray-50 min-h-screen flex flex-col">
      <Navbar />
      <div className="flex flex-1">
        <Sidebar />
        <main className="flex-1 ml-64 p-6">
          <div className="max-w-7xl mx-auto">
            {/* 错误提示 */}
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg"
              >
                <div className="flex items-center">
                  <FaTimes className="text-red-500 mr-3" />
                  <div>
                    <h3 className="text-sm font-medium text-red-800">错误</h3>
                    <p className="text-sm text-red-700 mt-1">{error}</p>
                  </div>
                  <button
                    onClick={() => setError(null)}
                    className="ml-auto text-red-500 hover:text-red-700"
                  >
                    <FaTimes />
                  </button>
                </div>
              </motion.div>
            )}

            {/* 页面标题和操作按钮 */}
            <div className="flex flex-col md:flex-row md:items-center md:justify-between mb-6">
              <div className="flex items-center mb-4 md:mb-0">
                <FaFolder className="text-blue-600 text-2xl mr-3" />
                <h1 className="text-2xl font-bold text-gray-900">知识库管理</h1>
              </div>
              <div className="flex gap-2">
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => setIsGlobalSearchOpen(true)}
                  className="flex items-center px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
                >
                  <FaSearch className="mr-2" />
                  全局搜索
                </motion.button>
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => setIsCreateModalOpen(true)}
                  className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                >
                  <FaPlus className="mr-2" />
                  创建知识库
                </motion.button>
              </div>
            </div>

            {/* 搜索和筛选 */}
            <div className="bg-white rounded-lg shadow-sm p-4 mb-6">
              <div className="flex flex-col lg:flex-row gap-4">
                <div className="flex-1">
                  <div className="relative">
                    <FaSearch className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" />
                    <input
                      type="text"
                      placeholder="搜索知识库名称或描述..."
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    />
                  </div>
                </div>
                <div className="flex gap-2">
                  <select
                    value={statusFilter}
                    onChange={(e) => {
                      setStatusFilter(e.target.value as 'all' | 'active' | 'archived');
                      setCurrentPage(1);
                    }}
                    className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="all">全部状态</option>
                    <option value="active">活跃</option>
                    <option value="archived">已归档</option>
                  </select>
                </div>
              </div>
            </div>

            {/* 加载状态 */}
            {loading && (
              <div className="flex justify-center items-center py-12">
                <FaSpinner className="animate-spin text-blue-600 text-2xl mr-3" />
                <span className="text-gray-600">加载中...</span>
              </div>
            )}

            {/* 知识库网格 */}
            {!loading && (
              <>
                {filteredKnowledgeBases.length > 0 ? (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-6">
                    {filteredKnowledgeBases.map((kb) => (
                      <motion.div
                        key={kb.id}
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="bg-white rounded-lg shadow-sm hover:shadow-md transition-shadow p-6"
                      >
                        <div className="flex items-start justify-between mb-4">
                          <div className="flex items-center">
                            <FaFolder className="text-blue-600 text-2xl mr-3" />
                            <div>
                              <h3 className="text-lg font-semibold text-gray-900">
                                {kb.name}
                              </h3>
                              <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium mt-1 ${
                                kb.status === 'active'
                                  ? 'bg-green-100 text-green-800'
                                  : 'bg-gray-100 text-gray-800'
                              }`}>
                                {kb.status === 'active' ? (
                                  <>
                                    <FaCheckCircle className="mr-1" />
                                    活跃
                                  </>
                                ) : (
                                  <>
                                    <FaArchive className="mr-1" />
                                    已归档
                                  </>
                                )}
                              </span>
                            </div>
                          </div>
                        </div>

                        <p className="text-sm text-gray-600 mb-4 line-clamp-2">
                          {kb.description || '暂无描述'}
                        </p>

                        <div className="grid grid-cols-3 gap-4 mb-4 text-center">
                          <div>
                            <div className="text-2xl font-bold text-blue-600">
                              {kb.totalDocuments || 0}
                            </div>
                            <div className="text-xs text-gray-500">文档</div>
                          </div>
                          <div>
                            <div className="text-2xl font-bold text-green-600">
                              {kb.publishedDocuments || 0}
                            </div>
                            <div className="text-xs text-gray-500">已发布</div>
                          </div>
                          <div>
                            <div className="text-2xl font-bold text-purple-600">
                              {kb.totalVectors || 0}
                            </div>
                            <div className="text-xs text-gray-500">向量</div>
                          </div>
                        </div>

                        <div className="text-xs text-gray-500 mb-4">
                          更新于 {formatDate(kb.updatedAt)}
                        </div>

                        <div className="flex justify-end space-x-2 pt-4 border-t border-gray-200">
                          <motion.button
                            whileHover={{ scale: 1.1 }}
                            whileTap={{ scale: 0.9 }}
                            onClick={() => handleViewKnowledgeBase(kb.id)}
                            className="p-2 text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                            title="查看"
                          >
                            <FaEye />
                          </motion.button>
                          <motion.button
                            whileHover={{ scale: 1.1 }}
                            whileTap={{ scale: 0.9 }}
                            onClick={() => openEditModal(kb)}
                            className="p-2 text-green-600 hover:bg-green-50 rounded-lg transition-colors"
                            title="编辑"
                          >
                            <FaEdit />
                          </motion.button>
                          <motion.button
                            whileHover={{ scale: 1.1 }}
                            whileTap={{ scale: 0.9 }}
                            onClick={() => handleVectorizeKnowledgeBase(kb.id, kb.name)}
                            className="p-2 text-purple-600 hover:bg-purple-50 rounded-lg transition-colors"
                            title="向量化"
                          >
                            <FaSpinner />
                          </motion.button>
                          <motion.button
                            whileHover={{ scale: 1.1 }}
                            whileTap={{ scale: 0.9 }}
                            onClick={() => openDeleteModal(kb)}
                            className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                            title="删除"
                          >
                            <FaTrash />
                          </motion.button>
                        </div>
                      </motion.div>
                    ))}
                  </div>
                ) : (
                  <div className="bg-white rounded-lg shadow-sm p-12 text-center">
                    <FaFolder className="mx-auto h-16 w-16 text-gray-400 mb-4" />
                    <h3 className="text-lg font-medium text-gray-900 mb-2">
                      没有找到知识库
                    </h3>
                    <p className="text-gray-500 mb-4">
                      {searchTerm ? '尝试调整搜索条件' : '开始创建您的第一个知识库'}
                    </p>
                    {!searchTerm && (
                      <motion.button
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        onClick={() => setIsCreateModalOpen(true)}
                        className="inline-flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                      >
                        <FaPlus className="mr-2" />
                        创建知识库
                      </motion.button>
                    )}
                  </div>
                )}

                {/* 分页 */}
                {totalPages > 1 && (
                  <div className="flex justify-center items-center space-x-2">
                    <button
                      onClick={() => setCurrentPage(prev => Math.max(1, prev - 1))}
                      disabled={currentPage === 1}
                      className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      上一页
                    </button>
                    <span className="text-gray-600">
                      第 {currentPage} / {totalPages} 页（共 {totalCount} 个）
                    </span>
                    <button
                      onClick={() => setCurrentPage(prev => Math.min(totalPages, prev + 1))}
                      disabled={currentPage === totalPages}
                      className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      下一页
                    </button>
                  </div>
                )}
              </>
            )}

            {/* 创建/编辑模态框 */}
            {(isCreateModalOpen || isEditModalOpen) && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4"
              >
                <motion.div
                  initial={{ opacity: 0, y: -20 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="bg-white rounded-xl shadow-xl w-full max-w-md p-6"
                >
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">
                    {isCreateModalOpen ? '创建知识库' : '编辑知识库'}
                  </h3>

                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (isCreateModalOpen) {
                        handleCreateKnowledgeBase();
                      } else {
                        handleUpdateKnowledgeBase();
                      }
                    }}
                    className="space-y-4"
                  >
                    <div>
                      <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">
                        名称 <span className="text-red-500">*</span>
                      </label>
                      <input
                        type="text"
                        id="name"
                        value={formData.name}
                        onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
                        className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                        required
                      />
                    </div>

                    <div>
                      <label htmlFor="description" className="block text-sm font-medium text-gray-700 mb-1">
                        描述
                      </label>
                      <textarea
                        id="description"
                        value={formData.description}
                        onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
                        rows={3}
                        className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      />
                    </div>

                    <div>
                      <label htmlFor="embeddingModel" className="block text-sm font-medium text-gray-700 mb-1">
                        嵌入模型
                      </label>
                      <select
                        id="embeddingModel"
                        value={formData.embeddingModel}
                        onChange={(e) => setFormData(prev => ({ ...prev, embeddingModel: e.target.value }))}
                        className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                        required
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
                        {embeddingModels.length > 0 ? `共 ${embeddingModels.length} 个可用模型` : '请先在"模型管理"中添加向量模型'}
                      </p>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        状态
                      </label>
                      <div className="space-y-2">
                        <label className="flex items-center">
                          <input
                            type="radio"
                            value="active"
                            checked={formData.status === 'active'}
                            onChange={(e) => setFormData(prev => ({ ...prev, status: e.target.value as 'active' | 'archived' }))}
                            className="mr-2"
                          />
                          活跃
                        </label>
                        <label className="flex items-center">
                          <input
                            type="radio"
                            value="archived"
                            checked={formData.status === 'archived'}
                            onChange={(e) => setFormData(prev => ({ ...prev, status: e.target.value as 'active' | 'archived' }))}
                            className="mr-2"
                          />
                          已归档
                        </label>
                      </div>
                    </div>

                    <div className="flex justify-end space-x-3 pt-4 border-t border-gray-200">
                      <button
                        type="button"
                        onClick={() => {
                          setIsCreateModalOpen(false);
                          setIsEditModalOpen(false);
                          setSelectedKnowledgeBase(null);
                          resetForm();
                        }}
                        className="px-4 py-2 border border-gray-300 rounded-lg font-medium text-gray-700 hover:bg-gray-50"
                      >
                        取消
                      </button>
                      <button
                        type="submit"
                        className="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700"
                      >
                        {isCreateModalOpen ? '创建' : '更新'}
                      </button>
                    </div>
                  </form>
                </motion.div>
              </motion.div>
            )}

            {/* 删除确认模态框 */}
            {isDeleteModalOpen && kbToDelete && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4"
              >
                <motion.div
                  initial={{ opacity: 0, y: -20 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="bg-white rounded-xl shadow-xl w-full max-w-md p-6"
                >
                  <div className="flex items-center mb-4">
                    <FaExclamationTriangle className="text-red-600 text-2xl mr-3" />
                    <h3 className="text-lg font-semibold text-gray-900">
                      确认删除
                    </h3>
                  </div>

                  <p className="text-gray-600 mb-4">
                    确定要删除知识库 <strong>{kbToDelete.name}</strong> 吗？
                  </p>

                  {kbToDelete.totalDocuments && kbToDelete.totalDocuments > 0 && (
                    <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 mb-4">
                      <p className="text-sm text-yellow-800">
                        <FaExclamationTriangle className="inline mr-2" />
                        此操作将同时删除该知识库中的 <strong>{kbToDelete.totalDocuments}</strong> 个文档及其向量数据，且无法恢复。
                      </p>
                    </div>
                  )}

                  <div className="flex justify-end space-x-3">
                    <button
                      onClick={() => {
                        setIsDeleteModalOpen(false);
                        setKbToDelete(null);
                      }}
                      className="px-4 py-2 border border-gray-300 rounded-lg font-medium text-gray-700 hover:bg-gray-50"
                    >
                      取消
                    </button>
                    <button
                      onClick={handleDeleteKnowledgeBase}
                      className="px-4 py-2 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700"
                    >
                      确认删除
                    </button>
                  </div>
                </motion.div>
              </motion.div>
            )}

            {/* 全局搜索模态框 */}
            <SearchModal
              isOpen={isGlobalSearchOpen}
              onClose={() => setIsGlobalSearchOpen(false)}
              onResultClick={(result) => {
                // 导航到文档所在的知识库
                navigate(`/knowledge/${result.document.kbId}`);
              }}
            />
          </div>
        </main>
      </div>
    </div>
  );
};

export default KnowledgeBaseList;
