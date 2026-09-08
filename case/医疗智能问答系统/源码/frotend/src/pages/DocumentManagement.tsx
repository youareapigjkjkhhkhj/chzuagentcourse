import React, { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/authContext';
import Navbar from '../components/Navbar';
import Sidebar from '../components/Sidebar';
import SearchModal from '../components/SearchModal';
import {
  FaFile,
  FaPlus,
  FaSearch,
  FaEdit,
  FaTrash,
  FaUpload,
  FaFileArchive,
  FaCheck,
  FaTimes,
  FaSpinner,
  FaExclamationTriangle,
  FaArrowLeft,
  FaDatabase,
  FaCheckCircle,
  FaClock,
  FaTimesCircle
} from 'react-icons/fa';
import { documentAPI, knowledgeBaseAPI } from '../services/api';
import { DocumentModal, FileUploadModal } from '../components/DocumentModals';

// 文档接口
interface Document {
  id: string;
  kbId: string;
  title: string;
  content: string;
  category: string;
  tags: string[];
  author: string;
  views: number;
  status: 'draft' | 'processing' | 'published' | 'failed';
  fileName?: string;
  fileType?: string;
  fileSize?: number;
  chunkCount: number;
  vectorStatus: 'pending' | 'processing' | 'completed' | 'failed';
  vectorError?: string;
  createdAt: string;
  updatedAt: string;
}

// 知识库接口
interface KnowledgeBase {
  id: string;
  name: string;
  description: string;
  embeddingModel: string;
  status: 'active' | 'archived';
}

const DocumentManagement: React.FC = () => {
  const { kbId } = useParams<{ kbId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();

  // 状态管理
  const [knowledgeBase, setKnowledgeBase] = useState<KnowledgeBase | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [filteredDocuments, setFilteredDocuments] = useState<Document[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'draft' | 'published' | 'processing' | 'failed'>('all');
  const [categoryFilter, setCategoryFilter] = useState('全部');
  const [sortBy, setSortBy] = useState<'title' | 'createdAt' | 'views'>('createdAt');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([]);
  
  // 分页
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const itemsPerPage = 20;

  // 加载状态
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  // 模态框状态
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [isZipUploadModalOpen, setIsZipUploadModalOpen] = useState(false);
  const [selectedDocument, setSelectedDocument] = useState<Document | null>(null);
  const [isSearchModalOpen, setIsSearchModalOpen] = useState(false);

  // 表单数据
  const [formData, setFormData] = useState({
    title: '',
    content: '',
    category: '',
    tags: [] as string[],
    status: 'draft' as 'draft' | 'published'
  });
  const [tagInput, setTagInput] = useState('');

  // 文件上传
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploading, setUploading] = useState(false);

  // 分类列表
  const [categories, setCategories] = useState<string[]>(['全部']);

  // 默认分类列表
  const defaultCategories = ['疾病知识', '药物信息', '诊疗指南', '康复护理', '预防保健'];

  // 搜索防抖
  const searchTimeout = useRef<number | null>(null);

  // 初始化加载
  useEffect(() => {
    if (kbId) {
      loadInitialData();
    }
  }, [kbId]);

  // 过滤和排序
  useEffect(() => {
    let filtered = documents.filter(doc => {
      const matchesSearch = doc.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
                           doc.content.toLowerCase().includes(searchTerm.toLowerCase()) ||
                           doc.tags.some(tag => tag.toLowerCase().includes(searchTerm.toLowerCase()));
      const matchesStatus = statusFilter === 'all' || doc.status === statusFilter;
      const matchesCategory = categoryFilter === '全部' || doc.category === categoryFilter;
      return matchesSearch && matchesStatus && matchesCategory;
    });

    // 排序
    filtered.sort((a, b) => {
      let compareValue = 0;
      if (sortBy === 'title') {
        compareValue = a.title.localeCompare(b.title);
      } else if (sortBy === 'createdAt') {
        compareValue = new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime();
      } else if (sortBy === 'views') {
        compareValue = a.views - b.views;
      }
      return sortOrder === 'asc' ? compareValue : -compareValue;
    });

    setFilteredDocuments(filtered);
  }, [documents, searchTerm, statusFilter, categoryFilter, sortBy, sortOrder]);

  const loadInitialData = async () => {
    try {
      setLoading(true);
      setError(null);

      // 初始化默认分类
      const uniqueCategories = ['全部', ...defaultCategories] as string[];
      setCategories(uniqueCategories);

      // 加载知识库信息
      const kbResponse = await knowledgeBaseAPI.getKnowledgeBase(kbId!);
      if (kbResponse.success && kbResponse.data) {
        setKnowledgeBase(kbResponse.data.knowledgeBase);
      }

      // 加载文档列表
      await loadDocuments();
    } catch (error) {
      console.error('加载数据失败:', error);
      setError('加载数据失败，请刷新页面重试');
    } finally {
      setLoading(false);
    }
  };

  const loadDocuments = async () => {
    try {
      const response = await documentAPI.getDocuments(kbId!, {
        page: currentPage,
        per_page: itemsPerPage,
        status: statusFilter === 'all' ? undefined : statusFilter
      });

      if (response.success && response.data) {
        const docs = response.data.documents || [];
        setDocuments(docs);

        // 提取分类，如果没有文档则使用默认分类
        if (docs.length > 0) {
          const docCategories = docs.map((d: Document) => d.category).filter(Boolean);
          const uniqueCategories = ['全部', ...new Set([...defaultCategories, ...docCategories])] as string[];
          setCategories(uniqueCategories);
        } else {
          // 没有文档时，使用默认分类
          const uniqueCategories = ['全部', ...defaultCategories] as string[];
          setCategories(uniqueCategories);
        }

        if (response.data.pagination) {
          setTotalPages(response.data.pagination.pages);
          setTotalCount(response.data.pagination.total);
        }
      }
    } catch (error) {
      console.error('加载文档列表失败:', error);
      setError('加载文档列表失败');
      // 即使加载失败，也设置默认分类
      const uniqueCategories = ['全部', ...defaultCategories] as string[];
      setCategories(uniqueCategories);
    }
  };

  const handleCreateDocument = async () => {
    if (!formData.title.trim() || !formData.content.trim()) {
      setError('请填写标题和内容');
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const response = await documentAPI.createDocument(kbId!, {
        title: formData.title,
        content: formData.content,
        category: formData.category,
        tags: formData.tags,
        status: formData.status
      });

      if (response.success) {
        setIsCreateModalOpen(false);
        resetForm();
        await loadDocuments();
      }
    } catch (error) {
      console.error('创建文档失败:', error);
      setError('创建文档失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateDocument = async () => {
    if (!selectedDocument || !formData.title.trim() || !formData.content.trim()) {
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const response = await documentAPI.updateDocument(kbId!, selectedDocument.id, {
        title: formData.title,
        content: formData.content,
        category: formData.category,
        tags: formData.tags,
        status: formData.status
      });

      if (response.success) {
        setIsEditModalOpen(false);
        setSelectedDocument(null);
        resetForm();
        await loadDocuments();
      }
    } catch (error) {
      console.error('更新文档失败:', error);
      setError('更新文档失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteDocument = async (docId: string) => {
    if (!window.confirm('确定要删除这个文档吗？')) {
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const response = await documentAPI.deleteDocument(kbId!, docId);

      if (response.success) {
        await loadDocuments();
      }
    } catch (error) {
      console.error('删除文档失败:', error);
      setError('删除文档失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const handleBatchDelete = async () => {
    if (selectedDocuments.length === 0) return;

    if (!window.confirm(`确定要删除选中的 ${selectedDocuments.length} 个文档吗？`)) {
      return;
    }

    try {
      setLoading(true);
      setError(null);

      await documentAPI.batchOperate(kbId!, 'delete', selectedDocuments);
      setSelectedDocuments([]);
      await loadDocuments();
    } catch (error) {
      console.error('批量删除失败:', error);
      setError('批量删除失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const handleBatchStatusChange = async (status: 'draft' | 'published') => {
    if (selectedDocuments.length === 0) return;

    try {
      setLoading(true);
      setError(null);

      const operation = status === 'published' ? 'publish' : 'draft';
      await documentAPI.batchOperate(kbId!, operation, selectedDocuments);
      setSelectedDocuments([]);
      await loadDocuments();
    } catch (error) {
      console.error('批量更新状态失败:', error);
      setError('批量更新状态失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const handleBatchSyncVectors = async () => {
    if (selectedDocuments.length === 0) return;

    if (!window.confirm(`确定要同步选中的 ${selectedDocuments.length} 个文档的向量吗？`)) {
      return;
    }

    try {
      setLoading(true);
      setError(null);

      await documentAPI.batchOperate(kbId!, 'sync-vectors', selectedDocuments);
      setSelectedDocuments([]);
      await loadDocuments();
    } catch (error) {
      console.error('批量同步向量失败:', error);
      setError('批量同步向量失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async () => {
    if (!uploadFile) {
      setError('请选择文件');
      return;
    }

    try {
      setUploading(true);
      setError(null);
      setUploadProgress(0);

      const response = await documentAPI.uploadFile(kbId!, uploadFile, {
        title: formData.title,
        category: formData.category,
        tags: formData.tags,
        status: formData.status
      }, (progress) => {
        setUploadProgress(progress);
      });

      if (response.success) {
        setIsUploadModalOpen(false);
        setUploadFile(null);
        resetForm();
        await loadDocuments();
      }
    } catch (error) {
      console.error('文件上传失败:', error);
      setError('文件上传失败，请重试');
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  };

  const handleZipUpload = async () => {
    if (!uploadFile) {
      setError('请选择 ZIP 文件');
      return;
    }

    try {
      setUploading(true);
      setError(null);
      setUploadProgress(0);

      const response = await documentAPI.uploadZip(kbId!, uploadFile, {
        title: formData.title,
        category: formData.category,
        tags: formData.tags,
        status: formData.status
      }, (progress) => {
        setUploadProgress(progress);
      });

      if (response.success) {
        setIsZipUploadModalOpen(false);
        setUploadFile(null);
        resetForm();
        await loadDocuments();
        
        if (response.data?.successCount) {
          alert(`成功导入 ${response.data.successCount} 个文档`);
        }
      }
    } catch (error) {
      console.error('ZIP 上传失败:', error);
      setError('ZIP 上传失败，请重试');
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  };

  const handleSelectDocument = (docId: string) => {
    setSelectedDocuments(prev =>
      prev.includes(docId)
        ? prev.filter(id => id !== docId)
        : [...prev, docId]
    );
  };

  const handleSelectAll = () => {
    if (selectedDocuments.length === filteredDocuments.length) {
      setSelectedDocuments([]);
    } else {
      setSelectedDocuments(filteredDocuments.map(doc => doc.id));
    }
  };

  const handleAddTag = () => {
    if (tagInput.trim() && !formData.tags.includes(tagInput.trim())) {
      setFormData(prev => ({
        ...prev,
        tags: [...prev.tags, tagInput.trim()]
      }));
      setTagInput('');
    }
  };

  const handleRemoveTag = (tagToRemove: string) => {
    setFormData(prev => ({
      ...prev,
      tags: prev.tags.filter(tag => tag !== tagToRemove)
    }));
  };

  const openEditModal = (doc: Document) => {
    setSelectedDocument(doc);
    setFormData({
      title: doc.title,
      content: doc.content,
      category: doc.category,
      tags: [...doc.tags],
      status: doc.status === 'published' ? 'published' : 'draft'
    });
    setIsEditModalOpen(true);
  };

  const resetForm = () => {
    setFormData({
      title: '',
      content: '',
      category: '',
      tags: [],
      status: 'draft'
    });
    setTagInput('');
    setSelectedDocument(null);
  };

  const formatDate = (dateString: string) => {
    const options: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'long', day: 'numeric' };
    return new Date(dateString).toLocaleDateString('zh-CN', options);
  };

  const getStatusBadge = (status: string) => {
    const badges = {
      draft: { color: 'bg-yellow-100 text-yellow-800', icon: FaClock, text: '草稿' },
      processing: { color: 'bg-blue-100 text-blue-800', icon: FaSpinner, text: '处理中' },
      published: { color: 'bg-green-100 text-green-800', icon: FaCheckCircle, text: '已发布' },
      failed: { color: 'bg-red-100 text-red-800', icon: FaTimesCircle, text: '失败' }
    };
    return badges[status as keyof typeof badges] || badges.draft;
  };

  const getVectorStatusBadge = (status: string) => {
    const badges = {
      pending: { color: 'bg-gray-100 text-gray-800', text: '待处理' },
      processing: { color: 'bg-blue-100 text-blue-800', text: '处理中' },
      completed: { color: 'bg-green-100 text-green-800', text: '已完成' },
      failed: { color: 'bg-red-100 text-red-800', text: '失败' }
    };
    return badges[status as keyof typeof badges] || badges.pending;
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

            {/* 警告提示 */}
            {warning && (
              <motion.div
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                className="mb-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg"
              >
                <div className="flex items-center">
                  <FaExclamationTriangle className="text-yellow-600 mr-3" />
                  <div className="flex-1">
                    <h3 className="text-sm font-medium text-yellow-800">警告</h3>
                    <p className="text-sm text-yellow-700 mt-1">{warning}</p>
                  </div>
                  <button
                    onClick={() => setWarning(null)}
                    className="text-yellow-600 hover:text-yellow-800"
                  >
                    <FaTimes />
                  </button>
                </div>
              </motion.div>
            )}

            {/* 页面标题 */}
            <div className="flex flex-col md:flex-row md:items-center md:justify-between mb-6">
              <div className="flex items-center mb-4 md:mb-0">
                <button
                  onClick={() => navigate('/knowledge')}
                  className="mr-4 p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  <FaArrowLeft />
                </button>
                <FaFile className="text-blue-600 text-2xl mr-3" />
                <div>
                  <h1 className="text-2xl font-bold text-gray-900">
                    {knowledgeBase?.name || '文档管理'}
                  </h1>
                  {knowledgeBase?.description && (
                    <p className="text-sm text-gray-600 mt-1">{knowledgeBase.description}</p>
                  )}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => setIsSearchModalOpen(true)}
                  className="flex items-center px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
                >
                  <FaSearch className="mr-2" />
                  搜索文档
                </motion.button>
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => setIsCreateModalOpen(true)}
                  className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                >
                  <FaPlus className="mr-2" />
                  创建文档
                </motion.button>
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => setIsUploadModalOpen(true)}
                  className="flex items-center px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
                >
                  <FaUpload className="mr-2" />
                  上传文件
                </motion.button>
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => setIsZipUploadModalOpen(true)}
                  className="flex items-center px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors"
                >
                  <FaFileArchive className="mr-2" />
                  批量导入
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
                      placeholder="搜索文档标题、内容或标签..."
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    />
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value as any)}
                    className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="all">全部状态</option>
                    <option value="draft">草稿</option>
                    <option value="processing">处理中</option>
                    <option value="published">已发布</option>
                    <option value="failed">失败</option>
                  </select>
                  <select
                    value={categoryFilter}
                    onChange={(e) => setCategoryFilter(e.target.value)}
                    className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  >
                    {categories.map(category => (
                      <option key={category} value={category}>{category}</option>
                    ))}
                  </select>
                  <select
                    value={`${sortBy}-${sortOrder}`}
                    onChange={(e) => {
                      const [sort, order] = e.target.value.split('-');
                      setSortBy(sort as any);
                      setSortOrder(order as any);
                    }}
                    className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="createdAt-desc">最新创建</option>
                    <option value="createdAt-asc">最早创建</option>
                    <option value="title-asc">标题 A-Z</option>
                    <option value="title-desc">标题 Z-A</option>
                    <option value="views-desc">浏览量最多</option>
                    <option value="views-asc">浏览量最少</option>
                  </select>
                </div>
              </div>
            </div>

            {/* 批量操作 */}
            {selectedDocuments.length > 0 && (
              <motion.div
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6"
              >
                <div className="flex flex-col sm:flex-row items-center justify-between">
                  <div className="mb-2 sm:mb-0">
                    <span className="text-blue-800 font-medium">
                      已选择 {selectedDocuments.length} 个文档
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <motion.button
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                      onClick={handleBatchSyncVectors}
                      className="flex items-center px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors text-sm"
                    >
                      <FaDatabase className="mr-1" />
                      同步向量
                    </motion.button>
                    <motion.button
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                      onClick={() => handleBatchStatusChange('published')}
                      className="flex items-center px-3 py-1 bg-green-600 text-white rounded hover:bg-green-700 transition-colors text-sm"
                    >
                      <FaCheck className="mr-1" />
                      批量发布
                    </motion.button>
                    <motion.button
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                      onClick={() => handleBatchStatusChange('draft')}
                      className="flex items-center px-3 py-1 bg-yellow-600 text-white rounded hover:bg-yellow-700 transition-colors text-sm"
                    >
                      <FaTimes className="mr-1" />
                      转为草稿
                    </motion.button>
                    <motion.button
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                      onClick={handleBatchDelete}
                      className="flex items-center px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700 transition-colors text-sm"
                    >
                      <FaTrash className="mr-1" />
                      批量删除
                    </motion.button>
                  </div>
                </div>
              </motion.div>
            )}

            {/* 加载状态 */}
            {loading && (
              <div className="flex justify-center items-center py-12">
                <FaSpinner className="animate-spin text-blue-600 text-2xl mr-3" />
                <span className="text-gray-600">加载中...</span>
              </div>
            )}

            {/* 文档列表 */}
            {!loading && (
              <div className="bg-white rounded-lg shadow-sm overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-6 py-3 text-left">
                          <input
                            type="checkbox"
                            checked={selectedDocuments.length === filteredDocuments.length && filteredDocuments.length > 0}
                            onChange={handleSelectAll}
                            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                          />
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          标题
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          分类
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          标签
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          状态
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          向量状态
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          更新时间
                        </th>
                        <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                          操作
                        </th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {filteredDocuments.length > 0 ? (
                        filteredDocuments.map((doc) => {
                          const statusBadge = getStatusBadge(doc.status);
                          const vectorBadge = getVectorStatusBadge(doc.vectorStatus);
                          const StatusIcon = statusBadge.icon;

                          return (
                            <tr key={doc.id} className="hover:bg-gray-50">
                              <td className="px-6 py-4">
                                <input
                                  type="checkbox"
                                  checked={selectedDocuments.includes(doc.id)}
                                  onChange={() => handleSelectDocument(doc.id)}
                                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                />
                              </td>
                              <td className="px-6 py-4">
                                <div className="text-sm font-medium text-gray-900">
                                  {doc.title}
                                </div>
                                {doc.fileName && (
                                  <div className="text-xs text-gray-500 mt-1">
                                    文件: {doc.fileName}
                                  </div>
                                )}
                              </td>
                              <td className="px-6 py-4">
                                {doc.category && (
                                  <span className="px-2 py-1 inline-flex text-xs leading-5 font-semibold rounded-full bg-blue-100 text-blue-800 whitespace-nowrap">
                                    {doc.category}
                                  </span>
                                )}
                              </td>
                              <td className="px-6 py-4">
                                <div className="flex flex-wrap gap-1">
                                  {doc.tags.map((tag, index) => (
                                    <span key={index} className="px-2 py-1 inline-flex text-xs leading-5 font-semibold rounded-full bg-gray-100 text-gray-800 whitespace-nowrap">
                                      {tag}
                                    </span>
                                  ))}
                                </div>
                              </td>
                              <td className="px-6 py-4">
                                <span className={`px-2 py-1 inline-flex items-center text-xs leading-5 font-semibold rounded-full whitespace-nowrap ${statusBadge.color}`}>
                                  <StatusIcon className="mr-1" />
                                  {statusBadge.text}
                                </span>
                              </td>
                              <td className="px-6 py-4">
                                <span className={`px-2 py-1 inline-flex text-xs leading-5 font-semibold rounded-full whitespace-nowrap ${vectorBadge.color}`}>
                                  {vectorBadge.text}
                                </span>
                                {doc.chunkCount > 0 && (
                                  <div className="text-xs text-gray-500 mt-1">
                                    {doc.chunkCount} 个向量块
                                  </div>
                                )}
                              </td>
                              <td className="px-6 py-4 text-sm text-gray-500 whitespace-nowrap">
                                {formatDate(doc.updatedAt)}
                              </td>
                              <td className="px-6 py-4 text-right text-sm font-medium">
                                <div className="flex justify-end space-x-2">
                                  <motion.button
                                    whileHover={{ scale: 1.1 }}
                                    whileTap={{ scale: 0.9 }}
                                    onClick={() => openEditModal(doc)}
                                    className="text-blue-600 hover:text-blue-900"
                                    title="编辑"
                                  >
                                    <FaEdit />
                                  </motion.button>
                                  <motion.button
                                    whileHover={{ scale: 1.1 }}
                                    whileTap={{ scale: 0.9 }}
                                    onClick={() => handleDeleteDocument(doc.id)}
                                    className="text-red-600 hover:text-red-900"
                                    title="删除"
                                  >
                                    <FaTrash />
                                  </motion.button>
                                </div>
                              </td>
                            </tr>
                          );
                        })
                      ) : (
                        <tr>
                          <td colSpan={8} className="px-6 py-12 text-center">
                            <div className="text-gray-500">
                              <FaFile className="mx-auto h-12 w-12 text-gray-400 mb-3" />
                              <p>没有找到匹配的文档</p>
                            </div>
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                {/* 分页 */}
                {totalPages > 1 && (
                  <div className="flex justify-center items-center space-x-2 p-4 border-t border-gray-200">
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
              </div>
            )}

            {/* 创建文档模态框 */}
            <DocumentModal
              isOpen={isCreateModalOpen}
              onClose={() => {
                setIsCreateModalOpen(false);
                resetForm();
              }}
              onSubmit={handleCreateDocument}
              formData={formData}
              setFormData={setFormData}
              tagInput={tagInput}
              setTagInput={setTagInput}
              onAddTag={handleAddTag}
              onRemoveTag={handleRemoveTag}
              categories={categories}
              title="创建文档"
              loading={loading}
            />

            {/* 编辑文档模态框 */}
            <DocumentModal
              isOpen={isEditModalOpen}
              onClose={() => {
                setIsEditModalOpen(false);
                setSelectedDocument(null);
                resetForm();
              }}
              onSubmit={handleUpdateDocument}
              formData={formData}
              setFormData={setFormData}
              tagInput={tagInput}
              setTagInput={setTagInput}
              onAddTag={handleAddTag}
              onRemoveTag={handleRemoveTag}
              categories={categories}
              title="编辑文档"
              loading={loading}
            />

            {/* 上传文件模态框 */}
            <FileUploadModal
              isOpen={isUploadModalOpen}
              onClose={() => {
                setIsUploadModalOpen(false);
                setUploadFile(null);
                resetForm();
              }}
              onSubmit={handleFileUpload}
              file={uploadFile}
              setFile={setUploadFile}
              formData={formData}
              setFormData={setFormData}
              tagInput={tagInput}
              setTagInput={setTagInput}
              onAddTag={handleAddTag}
              onRemoveTag={handleRemoveTag}
              categories={categories}
              uploading={uploading}
              uploadProgress={uploadProgress}
              title="上传文件"
              acceptedFormats=".txt,.md,.pdf,.docx,.xlsx,.pptx"
            />

            {/* 上传 ZIP 模态框 */}
            <FileUploadModal
              isOpen={isZipUploadModalOpen}
              onClose={() => {
                setIsZipUploadModalOpen(false);
                setUploadFile(null);
                resetForm();
              }}
              onSubmit={handleZipUpload}
              file={uploadFile}
              setFile={setUploadFile}
              formData={formData}
              setFormData={setFormData}
              tagInput={tagInput}
              setTagInput={setTagInput}
              onAddTag={handleAddTag}
              onRemoveTag={handleRemoveTag}
              categories={categories}
              uploading={uploading}
              uploadProgress={uploadProgress}
              title="批量导入 (ZIP)"
              acceptedFormats=".zip,.tar.gz"
            />

            {/* 搜索模态框 */}
            <SearchModal
              isOpen={isSearchModalOpen}
              onClose={() => setIsSearchModalOpen(false)}
              kbId={kbId}
              kbName={knowledgeBase?.name}
              onResultClick={(result) => {
                // 可以选择打开编辑模态框或者滚动到该文档
                const doc = documents.find(d => d.id === result.document.id);
                if (doc) {
                  openEditModal(doc);
                }
              }}
            />
          </div>
        </main>
      </div>
    </div>
  );
};

export default DocumentManagement;
