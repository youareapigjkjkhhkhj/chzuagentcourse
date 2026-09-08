import React, { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { useAuth } from '../contexts/authContext';
import Navbar from '../components/Navbar';
import Sidebar from '../components/Sidebar';
import { 
  FaBook, 
  FaPlus, 
  FaSearch, 
  FaEdit, 
  FaTrash, 
  FaCog, 
  FaDatabase,
  FaFilter,
  FaSortAmountDown,
  FaCheck,
  FaTimes,
  FaFileExport,
  FaFileImport,
  FaEye,
  FaDownload,
  FaSpinner,
  FaPlug,
  FaExclamationTriangle
} from 'react-icons/fa';
import { knowledgeAPI, modelAPI, transformKnowledgeArticle, vectorizationAPI } from '../services/api';
import { ModelConfig, ModelType } from '../types/model';
import { VectorizationProgress } from '../types/vectorization';
import VectorizationProgressModal from '../components/VectorizationProgressModal';
import DocumentVectorStatus from '../components/DocumentVectorStatus';

// 知识库文章接口
interface KnowledgeArticle {
  id: string;
  title: string;
  content: string;
  category: string;
  tags: string[];
  createdAt: string;
  updatedAt: string;
  author: string;
  views: number;
  status: 'published' | 'draft';
  vectorStatus?: 'pending' | 'processing' | 'completed' | 'failed';
  chunkCount?: number;
  vectorError?: string;
}

// 向量数据库类型 (pgvector is now the default)
type VectorDbType = 'pgvector';

// 向量数据库设置接口
interface VectorDbSettings {
  type: VectorDbType;
  embeddingModel: string;
  embeddingApiUrl?: string;
  embeddingDimension?: number;
  chunkSize: number;
  chunkOverlap: number;
  connectionString: string;
}

// 默认向量数据库设置
const defaultVectorDbSettings: VectorDbSettings = {
  type: 'pgvector',
  embeddingModel: '',
  embeddingApiUrl: '',
  embeddingDimension: 1536,
  chunkSize: 1000,
  chunkOverlap: 200,
  connectionString: ''
};

const KnowledgeBase: React.FC = () => {
  const { user } = useAuth();
  // 文章数据
  const [articles, setArticles] = useState<KnowledgeArticle[]>([]);

  // 过滤后的文章
  const [filteredArticles, setFilteredArticles] = useState<KnowledgeArticle[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('全部');
  const [sortBy, setSortBy] = useState<'title' | 'createdAt' | 'views'>('createdAt');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);
  const [selectedArticle, setSelectedArticle] = useState<KnowledgeArticle | null>(null);
  const [selectedArticles, setSelectedArticles] = useState<string[]>([]);
  const [formData, setFormData] = useState({
    title: '',
    content: '',
    category: '疾病知识',
    tags: [] as string[],
    status: 'draft' as 'published' | 'draft'
  });
  const [tagInput, setTagInput] = useState('');
  
  // 状态管理
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testingConnection, setTestingConnection] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [similarityThreshold, setSimilarityThreshold] = useState(0.3); // 添加相似度阈值状态
  
  // 向量化进度状态
  const [vectorizationProgress, setVectorizationProgress] = useState<VectorizationProgress>({
    status: 'idle',
    total: 0,
    processed: 0,
    successful: 0,
    failed: 0,
    currentDocument: null,
    errors: [],
    startTime: null,
    endTime: null
  });
  const [showProgressModal, setShowProgressModal] = useState(false);
  const [cancelRequested, setCancelRequested] = useState(false);
  
  // 向量数据库设置
  const [vectorDbSettings, setVectorDbSettings] = useState<VectorDbSettings>({
    type: 'pgvector',
    embeddingModel: '',
    embeddingApiUrl: '',
    embeddingDimension: 1536,
    chunkSize: 1000,
    chunkOverlap: 200,
    connectionString: ''
  });

  // 嵌入模型数据
  const [embeddingModels, setEmbeddingModels] = useState<ModelConfig[]>([]);
  const [availableCategories, setAvailableCategories] = useState<string[]>(['疾病知识', '药物信息', '诊疗指南', '康复护理', '预防保健']);
  
  // 搜索防抖
  const searchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 获取所有分类（防止API返回"全部"选项导致重复）
  const categories = availableCategories.includes('全部') 
    ? availableCategories 
    : ['全部', ...availableCategories];

  // 初始化数据加载
  useEffect(() => {
    loadInitialData();
  }, []);

  // 过滤和排序文章
  useEffect(() => {
    if (!articles.length && !loading) {
      setFilteredArticles([]);
      return;
    }

    let filtered = articles.filter(article => {
      const matchesSearch = article.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
                           article.content.toLowerCase().includes(searchTerm.toLowerCase()) ||
                           article.tags.some(tag => tag.toLowerCase().includes(searchTerm.toLowerCase()));
      const matchesCategory = selectedCategory === '全部' || article.category === selectedCategory;
      return matchesSearch && matchesCategory;
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

    setFilteredArticles(filtered);
  }, [articles, searchTerm, selectedCategory, sortBy, sortOrder, loading]);

  // 加载初始数据
  const loadInitialData = async () => {
    try {
      setLoading(true);
      setError(null);
      
      // 并行加载数据
      const [articlesResponse, categoriesResponse, modelsResponse, settingsResponse] = await Promise.allSettled([
        knowledgeAPI.getArticles(),
        knowledgeAPI.getCategories(),
        modelAPI.getModels(),
        knowledgeAPI.getSettings()
      ]);

      // 处理文章数据
      if (articlesResponse.status === 'fulfilled' && articlesResponse.value.success) {
        const backendArticles = articlesResponse.value.data.articles || [];
        setArticles(backendArticles.map((article: any) => transformKnowledgeArticle(article)));
      } else {
        console.error('获取文章列表失败:', articlesResponse);
        setArticles([]);
      }

      // 处理分类数据
      if (categoriesResponse.status === 'fulfilled' && categoriesResponse.value.success) {
        const apiCategories = categoriesResponse.value.data.categories || [];
        // 合并默认分类和API返回的分类，去重
        const defaultCategories = ['疾病知识', '药物信息', '诊疗指南', '康复护理', '预防保健'];
        const allCategories = [...new Set([...defaultCategories, ...apiCategories])];
        setAvailableCategories(allCategories);
      } else {
        console.error('获取分类列表失败:', categoriesResponse);
        // 保持默认分类
        setAvailableCategories(['疾病知识', '药物信息', '诊疗指南', '康复护理', '预防保健']);
      }

      // 处理模型数据 - 只获取嵌入模型（向量模型）
      let embeddingModelsList: ModelConfig[] = [];
      if (modelsResponse.status === 'fulfilled' && modelsResponse.value.success) {
        const allModels = modelsResponse.value.data.models || [];
        embeddingModelsList = allModels.filter((model: ModelConfig) => 
          model.type === ModelType.EMBEDDING
        );

        // 如果后端已保存的模型不在过滤结果里，也把它加进来，避免丢失
        // 这通常是 .env 中配置的默认模型
        const settings = settingsResponse.status === 'fulfilled' && settingsResponse.value.success
          ? settingsResponse.value.data.settings || {}
          : {};
        const savedModel = settings.embeddingModel;
        if (savedModel && !embeddingModelsList.some(m => m.modelName === savedModel)) {
          // 构造一个临时 ModelConfig，保证下拉列表里始终有当前值
          // 这是 .env 中的默认模型
          embeddingModelsList.unshift({
            modelName: savedModel,
            provider: 'default (.env)',
            type: ModelType.EMBEDDING,
            isActive: true,
            apiEndpoint: settings.embeddingApiUrl || ''
          } as ModelConfig);
          console.log('[KB] loadInitialData: added default model from .env', savedModel);
        }

        setEmbeddingModels(embeddingModelsList);
        console.log('[KB] loadInitialData: loaded embedding models', embeddingModelsList.length);
      } else {
        console.error('获取模型列表失败:', modelsResponse);
        setEmbeddingModels([]);
      }

      // 处理设置数据
      if (settingsResponse.status === 'fulfilled' && settingsResponse.value.success && settingsResponse.value.data) {
        const settings = settingsResponse.value.data.settings || {};
        console.log('[KB] loadInitialData: loaded settings', settings);
        
        // 将设置数据映射到组件状态
        setVectorDbSettings({
          type: 'pgvector',
          embeddingModel: settings.embeddingModel || (embeddingModelsList.length > 0 ? embeddingModelsList[0].modelName : ''),
          embeddingApiUrl: settings.embeddingApiUrl || '',
          embeddingDimension: settings.embeddingDimension || 1536,
          chunkSize: settings.chunkSize || 1000,
          chunkOverlap: settings.chunkOverlap || 200,
          connectionString: settings.connectionString || ''
        });
      } else {
        console.log('[KB] loadInitialData: no settings found or error', settingsResponse);
        // 设置默认值
        const defaultModel = embeddingModelsList.length > 0 ? embeddingModelsList[0] : null;
        let defaultApiUrl = '';
        if (defaultModel && defaultModel.apiEndpoint) {
          defaultApiUrl = defaultModel.apiEndpoint;
          if (!defaultApiUrl.endsWith('/api/embeddings') && !defaultApiUrl.endsWith('/embeddings')) {
            defaultApiUrl = `${defaultApiUrl}/api/embeddings`;
          }
        }
        
        setVectorDbSettings({
          type: 'pgvector',
          embeddingModel: defaultModel ? defaultModel.modelName : '',
          embeddingApiUrl: defaultApiUrl,
          embeddingDimension: 1536,
          chunkSize: 1000,
          chunkOverlap: 200,
          connectionString: ''
        });
      }

    } catch (error) {
      console.error('加载初始数据失败:', error);
      setError('加载数据失败，请刷新页面重试');
      setArticles([]);
      // 保持默认分类
      setAvailableCategories(['疾病知识', '药物信息', '诊疗指南', '康复护理', '预防保健']);
      setEmbeddingModels([]);
    } finally {
      setLoading(false);
    }
  };

  // 重新加载文章列表
  const loadArticles = async () => {
    try {
      console.debug('[KB] loadArticles: start');
      const response = await knowledgeAPI.getArticles();
      if (response.success && response.data) {
        const list = response.data.articles ? response.data.articles.map((article: any) => transformKnowledgeArticle(article)) : [];
        console.debug('[KB] loadArticles: received', list.length, 'articles');
        setArticles(list);
      }
    } catch (error) {
      console.error('加载文章列表失败:', error);
      console.debug('[KB] loadArticles: error', error);
      setError('加载文章失败');
    }
  };

  // 重新加载分类列表
  const loadCategories = async () => {
    try {
      console.debug('[KB] loadCategories: start');
      const response = await knowledgeAPI.getCategories();
      if (response.success && response.data) {
        const apiCategories = response.data.categories || [];
        console.debug('[KB] loadCategories: received', apiCategories.length, 'categories');
        // 合并默认分类和API返回的分类，去重
        const defaultCategories = ['疾病知识', '药物信息', '诊疗指南', '康复护理', '预防保健'];
        const allCategories = [...new Set([...defaultCategories, ...apiCategories])];
        setAvailableCategories(allCategories);
      }
    } catch (error) {
      console.error('加载分类列表失败:', error);
      console.debug('[KB] loadCategories: error', error);
      // 保持默认分类
      setAvailableCategories(['疾病知识', '药物信息', '诊疗指南', '康复护理', '预防保健']);
    }
  };

  // 更新向量化进度
  const updateVectorizationProgress = (update: Partial<VectorizationProgress>) => {
    setVectorizationProgress(prev => ({
      ...prev,
      ...update
    }));
  };

  // 取消向量化任务
  const cancelVectorization = () => {
    setCancelRequested(true);
    updateVectorizationProgress({
      status: 'cancelled',
      endTime: Date.now()
    });
  };

  // 处理单文档向量化
  const handleVectorizeDocument = async (docId: string, docTitle: string) => {
    try {
      setError(null);
      
      // 初始化进度
      updateVectorizationProgress({
        status: 'processing',
        total: 1,
        processed: 0,
        successful: 0,
        failed: 0,
        currentDocument: docTitle,
        errors: [],
        startTime: Date.now(),
        endTime: null
      });
      
      setShowProgressModal(true);
      
      // 调用向量化API（假设知识库ID为'default'，实际应该从上下文获取）
      const response = await vectorizationAPI.vectorizeDocument('default', docId, {
        force: false
      });
      
      if (response.success) {
        updateVectorizationProgress({
          status: 'completed',
          processed: 1,
          successful: 1,
          endTime: Date.now()
        });
      } else {
        updateVectorizationProgress({
          status: 'error',
          processed: 1,
          failed: 1,
          errors: [{
            documentId: docId,
            title: docTitle,
            error: response.data?.message || '向量化失败'
          }],
          endTime: Date.now()
        });
      }
      
      // 刷新文章列表
      await loadArticles();
    } catch (error) {
      console.error('向量化文档失败:', error);
      
      // 提供友好的网络错误消息
      let errorMessage = '向量化失败';
      if (error instanceof TypeError && error.message.includes('fetch')) {
        errorMessage = '网络连接失败，请检查网络连接';
      } else if ((error as any)?.message) {
        errorMessage = (error as Error).message;
      }
      
      updateVectorizationProgress({
        status: 'error',
        processed: 1,
        failed: 1,
        errors: [{
          documentId: docId,
          title: docTitle,
          error: errorMessage
        }],
        endTime: Date.now()
      });
    }
  };

  // 处理批量向量化
  const handleBatchVectorize = async (documentIds: string[]) => {
    try {
      setError(null);
      setCancelRequested(false);
      
      // 初始化进度
      updateVectorizationProgress({
        status: 'processing',
        total: documentIds.length,
        processed: 0,
        successful: 0,
        failed: 0,
        currentDocument: null,
        errors: [],
        startTime: Date.now(),
        endTime: null
      });
      
      setShowProgressModal(true);
      
      // 获取要处理的文档信息
      const documentsToProcess = articles.filter(article => 
        documentIds.includes(article.id)
      );
      
      let processedCount = 0;
      let successCount = 0;
      let failedCount = 0;
      const errors: Array<{ documentId: string; title: string; error: string }> = [];
      
      // 逐个处理文档
      for (const doc of documentsToProcess) {
        // 检查是否请求取消
        if (cancelRequested) {
          updateVectorizationProgress({
            status: 'cancelled',
            processed: processedCount,
            successful: successCount,
            failed: failedCount,
            errors,
            endTime: Date.now()
          });
          return;
        }
        
        // 更新当前处理的文档
        updateVectorizationProgress({
          currentDocument: doc.title
        });
        
        try {
          // 调用向量化API（假设知识库ID为'default'）
          const response = await vectorizationAPI.vectorizeDocument('default', doc.id, {
            force: false
          });
          
          if (response.success) {
            successCount++;
          } else {
            failedCount++;
            errors.push({
              documentId: doc.id,
              title: doc.title,
              error: response.data?.message || '向量化失败'
            });
          }
        } catch (error) {
          failedCount++;
          
          // 提供友好的网络错误消息
          let errorMessage = '向量化失败';
          if (error instanceof TypeError && error.message.includes('fetch')) {
            errorMessage = '网络连接失败';
          } else if ((error as any)?.message) {
            errorMessage = (error as Error).message;
          }
          
          errors.push({
            documentId: doc.id,
            title: doc.title,
            error: errorMessage
          });
        }
        
        processedCount++;
        
        // 更新进度
        updateVectorizationProgress({
          processed: processedCount,
          successful: successCount,
          failed: failedCount,
          errors
        });
      }
      
      // 完成
      updateVectorizationProgress({
        status: 'completed',
        currentDocument: null,
        endTime: Date.now()
      });
      
      // 刷新文章列表
      await loadArticles();
    } catch (error) {
      console.error('批量向量化失败:', error);
      
      // 提供友好的错误消息
      let errorMessage = '批量向量化失败，请重试';
      if (error instanceof TypeError && error.message.includes('fetch')) {
        errorMessage = '网络连接失败，请检查网络连接后重试';
      }
      
      updateVectorizationProgress({
        status: 'error',
        endTime: Date.now()
      });
      setError(errorMessage);
    }
  };

  // 处理重试失败文档
  const handleRetryFailedDocuments = async (documentIds: string[]) => {
    // 关闭当前进度对话框
    setShowProgressModal(false);
    
    // 等待一小段时间让对话框关闭动画完成
    await new Promise(resolve => setTimeout(resolve, 300));
    
    // 重新开始向量化
    await handleBatchVectorize(documentIds);
  };

  // 处理添加文章
  const handleAddArticle = async () => {
    if (formData.title.trim() && formData.content.trim()) {
      try {
        setSaving(true);
        setError(null);
        setWarning(null);
        console.debug('[KB] createArticle: payload', {
          title: formData.title,
          category: formData.category,
          status: formData.status,
          tagsCount: formData.tags?.length || 0,
          author: user?.name || '未知用户',
        });
        
        const response = await knowledgeAPI.createArticle({
          title: formData.title,
          content: formData.content,
          category: formData.category,
          tags: formData.tags,
          status: formData.status,
          author: user?.name || '未知用户'
        });

        if (response.success) {
          console.debug('[KB] createArticle: success, reloading list');
          
          // 检查是否有向量同步警告
          if (response.data?.warning) {
            setWarning(response.data.warning);
          }
          
          // 重新加载文章列表和分类列表
          await Promise.all([
            loadArticles(),
            loadCategories()
          ]);
          setFormData({
            title: '',
            content: '',
            category: '疾病知识',
            tags: [],
            status: 'draft'
          });
          setIsAddModalOpen(false);
        } else {
          console.debug('[KB] createArticle: response not success');
          setError('添加文章失败');
        }
      } catch (error) {
        console.error('添加文章失败:', error);
        console.debug('[KB] createArticle: error', error);
        setError('添加文章失败，请重试');
      } finally {
        setSaving(false);
      }
    }
  };

  // 处理编辑文章
  const handleEditArticle = (article: KnowledgeArticle) => {
    setSelectedArticle(article);
    setFormData({
      title: article.title,
      content: article.content,
      category: article.category,
      tags: article.tags,
      status: article.status
    });
    setIsAddModalOpen(true);
  };

  // 处理更新文章
  const handleUpdateArticle = async () => {
    if (!selectedArticle || !formData.title.trim() || !formData.content.trim()) {
      return;
    }

    try {
      setSaving(true);
      setError(null);
      setWarning(null);
      
      const response = await knowledgeAPI.updateArticle(selectedArticle.id, {
        title: formData.title,
        content: formData.content,
        category: formData.category,
        tags: formData.tags,
        status: formData.status,
        author: user?.name || '未知用户'
      });

      if (response.success) {
        // 检查是否有向量同步警告
        if (response.data?.warning) {
          setWarning(response.data.warning);
        }
        
        // 重新加载文章列表和分类列表
        await Promise.all([
          loadArticles(),
          loadCategories()
        ]);
        setFormData({
          title: '',
          content: '',
          category: '疾病知识',
          tags: [],
          status: 'draft'
        });
        setSelectedArticle(null);
        setIsAddModalOpen(false);
      } else {
        setError('更新文章失败');
      }
    } catch (error) {
      console.error('更新文章失败:', error);
      setError('更新文章失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  // 处理删除文章
  const handleDeleteArticle = async (id: string) => {
    if (window.confirm('确定要删除这篇文章吗？')) {
      try {
        setSaving(true);
        setError(null);
        
        const response = await knowledgeAPI.deleteArticle(id);
        
        if (response.success) {
          // 重新加载文章列表
          await loadArticles();
        } else {
          setError('删除文章失败');
        }
      } catch (error) {
        console.error('删除文章失败:', error);
        setError('删除文章失败，请重试');
      } finally {
        setSaving(false);
      }
    }
  };

  // 处理批量删除
  const handleBatchDelete = async () => {
    if (selectedArticles.length === 0) return;
    
    if (window.confirm(`确定要删除选中的 ${selectedArticles.length} 篇文章吗？`)) {
      try {
        setSaving(true);
        setError(null);
        
        // 使用批量操作API
        await knowledgeAPI.batchOperate('delete', selectedArticles);
        
        // 重新加载文章列表
        await loadArticles();
        setSelectedArticles([]);
      } catch (error) {
        console.error('批量删除失败:', error);
        setError('批量删除失败，请重试');
      } finally {
        setSaving(false);
      }
    }
  };

  // 处理批量更改状态
  const handleBatchStatusChange = async (status: 'published' | 'draft') => {
    if (selectedArticles.length === 0) return;
    
    try {
      setSaving(true);
      setError(null);
      
      // 使用批量操作API
      const operation = status === 'published' ? 'publish' : 'draft';
      await knowledgeAPI.batchOperate(operation, selectedArticles);
      
      // 重新加载文章列表
      await loadArticles();
      setSelectedArticles([]);
    } catch (error) {
      console.error('批量更新状态失败:', error);
      setError('批量更新状态失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  // 处理选择/取消选择文章
  const handleSelectArticle = (id: string) => {
    setSelectedArticles(prev =>
      prev.includes(id)
        ? prev.filter(articleId => articleId !== id)
        : [...prev, id]
    );
  };

  // 处理全选/取消全选
  const handleSelectAll = () => {
    if (selectedArticles.length === filteredArticles.length) {
      setSelectedArticles([]);
    } else {
      setSelectedArticles(filteredArticles.map(article => article.id));
    }
  };

  // 处理添加标签
  const handleAddTag = () => {
    if (tagInput.trim() && !formData.tags.includes(tagInput.trim())) {
      setFormData(prev => ({
        ...prev,
        tags: [...prev.tags, tagInput.trim()]
      }));
      setTagInput('');
    }
  };

  // 处理删除标签
  const handleRemoveTag = (tagToRemove: string) => {
    setFormData(prev => ({
      ...prev,
      tags: prev.tags.filter(tag => tag !== tagToRemove)
    }));
  };

  // 处理搜索
  const handleSearch = async (term: string) => {
    setSearchTerm(term);
    if (term.trim()) {
      try {
        setSearching(true);
        const response = await knowledgeAPI.searchArticles(term, {
          // 不指定limit，让后端使用知识库设置中的默认值
          searchType: 'hybrid',
          similarityThreshold: similarityThreshold
        });
        if (response.success && response.data) {
          setArticles(response.data.results ? response.data.results.map((article: any) => transformKnowledgeArticle(article)) : []);
        }
      } catch (error) {
        console.error('搜索失败:', error);
        setError('搜索失败');
      } finally {
        setSearching(false);
      }
    } else {
      // 如果搜索词为空，重新加载所有文章
      await loadArticles();
    }
  };

  // 处理分类筛选
  const handleCategoryFilter = (category: string) => {
    setSelectedCategory(category);
  };

  // 处理保存设置
  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setSaving(true);
      setError(null);
      console.debug('[KB] saveSettings: payload', vectorDbSettings);
      
      const response = await knowledgeAPI.updateSettings(vectorDbSettings);
      
      if (response.success) {
        console.debug('[KB] saveSettings: success');
        alert('设置已保存！');
        setIsSettingsModalOpen(false);
      } else {
        console.debug('[KB] saveSettings: response not success', response);
        setError('保存设置失败');
      }
    } catch (error) {
      console.error('保存设置失败:', error);
      console.debug('[KB] saveSettings: error', error);
      setError('保存设置失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  // 测试嵌入模型连接
  const handleTestConnection = async () => {
    try {
      setTestingConnection(true);
      setError(null);
      
      if (!vectorDbSettings.embeddingModel) {
        alert('请先选择嵌入模型');
        return;
      }
      
      const response = await knowledgeAPI.testEmbedding({
        embeddingModel: vectorDbSettings.embeddingModel
      });
      
      // 后端统一使用success_response包装，真实结果在data中
      const testResult = response?.data ?? {};
      const available = !!testResult.available;
      
      if (available) {
        const dimension = testResult.dimension || '未知';
        const apiStyle = testResult.apiStyle || '未知';
        alert(`嵌入模型测试成功！\n模型: ${testResult.model}\n维度: ${dimension}\nAPI 风格: ${apiStyle}`);
      } else {
        const errorMsg = testResult.error || testResult.message || '未知错误';
        alert(`嵌入模型测试失败：${errorMsg}`);
      }
    } catch (error) {
      console.error('嵌入模型测试失败:', error);
      alert('连接测试失败：' + (error as Error).message);
    } finally {
      setTestingConnection(false);
    }
  };

  // 重置表单
  const resetForm = () => {
    setFormData({
      title: '',
      content: '',
      category: '疾病知识',
      tags: [],
      status: 'draft'
    });
    setTagInput('');
    setSelectedArticle(null);
  };

  // 打开编辑模态框
  const openEditModal = (article: KnowledgeArticle) => {
    setSelectedArticle(article);
    setFormData({
      title: article.title,
      content: article.content,
      category: article.category,
      tags: [...article.tags],
      status: article.status
    });
    setIsEditModalOpen(true);
  };

  // 同步向量数据库
  const handleSyncVectors = async (_force: boolean = false, selectedIds?: string[]) => {
    // 确定要向量化的文档ID列表
    const documentIds = selectedIds && selectedIds.length > 0 
      ? selectedIds 
      : articles.filter(a => a.status === 'published').map(a => a.id);
    
    if (documentIds.length === 0) {
      alert('没有可向量化的文档。请确保至少有一篇已发布的文章。');
      return;
    }
    
    // 调用批量向量化
    await handleBatchVectorize(documentIds);
  };

  // 格式化日期
  const formatDate = (dateString: string) => {
    const options: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'long', day: 'numeric' };
    return new Date(dateString).toLocaleDateString('zh-CN', options);
  };

  // 导出文章
  const exportArticle = (article: KnowledgeArticle) => {
    const dataStr = JSON.stringify(article, null, 2);
    const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
    
    const exportFileDefaultName = `${article.title}.json`;
    
    const linkElement = document.createElement('a');
    linkElement.setAttribute('href', dataUri);
    linkElement.setAttribute('download', exportFileDefaultName);
    linkElement.click();
  };

  // 批量导出
  const batchExport = () => {
    if (selectedArticles.length === 0) return;
    
    const selectedData = articles.filter(article => selectedArticles.includes(article.id));
    const dataStr = JSON.stringify(selectedData, null, 2);
    const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
    
    const exportFileDefaultName = `knowledge_base_${new Date().toISOString().split('T')[0]}.json`;
    
    const linkElement = document.createElement('a');
    linkElement.setAttribute('href', dataUri);
    linkElement.setAttribute('download', exportFileDefaultName);
    linkElement.click();
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
                  onClick={() => handleSyncVectors(false)}
                  disabled={syncing}
                  className="mr-2 px-3 py-1 bg-yellow-600 text-white rounded hover:bg-yellow-700 disabled:bg-gray-400 text-sm"
                >
                  {syncing ? '同步中...' : '立即同步'}
                </button>
                <button
                  onClick={() => setWarning(null)}
                  className="text-yellow-600 hover:text-yellow-800"
                >
                  <FaTimes />
                </button>
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

          {/* 主要内容区域 - 仅在非加载状态显示 */}
          {!loading && (
            <div>
            <div className="flex flex-col md:flex-row md:items-center md:justify-between mb-6">
              <div className="flex items-center mb-4 md:mb-0">
                <FaBook className="text-blue-600 text-2xl mr-3" />
                <h1 className="text-2xl font-bold text-gray-900">知识库管理</h1>
              </div>
              <div className="flex flex-wrap gap-2">
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => setIsAddModalOpen(true)}
                  className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                >
                  <FaPlus className="mr-2" />
                  添加文章
                </motion.button>
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => handleSyncVectors(false)}
                  disabled={syncing}
                  className="flex items-center px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors disabled:bg-gray-400 disabled:cursor-not-allowed"
                >
                  {syncing ? (
                    <>
                      <FaSpinner className="mr-2 animate-spin" />
                      同步中...
                    </>
                  ) : (
                    <>
                      <FaDatabase className="mr-2" />
                      同步向量库
                    </>
                  )}
                </motion.button>
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => setIsSettingsModalOpen(true)}
                  className="flex items-center px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 transition-colors"
                >
                  <FaCog className="mr-2" />
                  知识库设置
                </motion.button>
              </div>
            </div>

        {/* 搜索和筛选区域 */}
        <div className="bg-white rounded-lg shadow-sm p-4 mb-6">
          <div className="flex flex-col lg:flex-row gap-4">
            <div className="flex-1">
              <div className="relative">
                <FaSearch className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" />
                <input
                  type="text"
                  placeholder="搜索文章标题、内容或标签..."
                  value={searchTerm}
                  onChange={(e) => {
                    const value = e.target.value;
                    setSearchTerm(value);
                    // 防抖搜索
                    if (searchTimeout.current) {
                      clearTimeout(searchTimeout.current);
                    }
                    if (value.trim()) {
                      searchTimeout.current = setTimeout(() => {
                        handleSearch(value);
                      }, 500);
                    } else {
                      loadArticles();
                    }
                  }}
                  className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
                {searching && (
                  <FaSpinner className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 animate-spin" />
                )}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <select
                value={selectedCategory}
                onChange={(e) => setSelectedCategory(e.target.value)}
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
                  setSortBy(sort as 'title' | 'createdAt' | 'views');
                  setSortOrder(order as 'asc' | 'desc');
                }}
                className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              >
                <option value="createdAt-desc">最新发布</option>
                <option value="createdAt-asc">最早发布</option>
                <option value="title-asc">标题 A-Z</option>
                <option value="title-desc">标题 Z-A</option>
                <option value="views-desc">浏览量最多</option>
                <option value="views-asc">浏览量最少</option>
              </select>
            </div>
          </div>
          {/* 相似度阈值控制 */}
          <div className="mt-4 pt-4 border-t border-gray-200">
            <div className="flex items-center gap-4">
              <label className="text-sm font-medium text-gray-700 min-w-0">
                相似度阈值: <span className="text-blue-600">{similarityThreshold.toFixed(2)}</span>
              </label>
              <input
                type="range"
                min="0.1"
                max="1.0"
                step="0.05"
                value={similarityThreshold}
                onChange={(e) => setSimilarityThreshold(parseFloat(e.target.value))}
                className="flex-1"
              />
              <span className="text-xs text-gray-500">
                {similarityThreshold < 0.4 ? '更宽松' : similarityThreshold > 0.7 ? '更严格' : '适中'}
              </span>
            </div>
          </div>
        </div>

        {/* 批量操作区域 */}
        {selectedArticles.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6"
          >
            <div className="flex flex-col sm:flex-row items-center justify-between">
              <div className="mb-2 sm:mb-0">
                <span className="text-blue-800 font-medium">
                  已选择 {selectedArticles.length} 篇文章
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => handleSyncVectors(false, selectedArticles)}
                  disabled={syncing}
                  className="flex items-center px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors text-sm disabled:bg-gray-400"
                >
                  {syncing ? <FaSpinner className="mr-1 animate-spin" /> : <FaDatabase className="mr-1" />}
                  同步选中
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
                  批量草稿
                </motion.button>
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={batchExport}
                  className="flex items-center px-3 py-1 bg-purple-600 text-white rounded hover:bg-purple-700 transition-colors text-sm"
                >
                  <FaFileExport className="mr-1" />
                  批量导出
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

        {/* 文章列表 */}
        <div className="bg-white rounded-lg shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left">
                    <input
                      type="checkbox"
                      checked={selectedArticles.length === filteredArticles.length && filteredArticles.length > 0}
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
                    作者
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    状态
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    向量化状态
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    浏览量
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
                {filteredArticles.length > 0 ? (
                  filteredArticles.map((article) => (
                    <tr key={article.id} className="hover:bg-gray-50">
                      <td className="px-6 py-4">
                        <input
                          type="checkbox"
                          checked={selectedArticles.includes(article.id)}
                          onChange={() => handleSelectArticle(article.id)}
                          className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                        />
                      </td>
                      <td className="px-6 py-4">
                        <div className="text-sm font-medium text-gray-900">
                          {article.title}
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <span className="px-2 py-1 inline-flex text-xs leading-5 font-semibold rounded-full bg-blue-100 text-blue-800 whitespace-nowrap">
                          {article.category}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex flex-wrap gap-1">
                          {article.tags.map((tag, index) => (
                            <span key={index} className="px-2 py-1 inline-flex text-xs leading-5 font-semibold rounded-full bg-gray-100 text-gray-800 whitespace-nowrap">
                              {tag}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-500 whitespace-nowrap">
                        {article.author}
                      </td>
                      <td className="px-6 py-4">
                        <span className={`px-2 py-1 inline-flex text-xs leading-5 font-semibold rounded-full whitespace-nowrap ${
                          article.status === 'published' 
                            ? 'bg-green-100 text-green-800' 
                            : 'bg-yellow-100 text-yellow-800'
                        }`}>
                          {article.status === 'published' ? '已发布' : '草稿'}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <DocumentVectorStatus
                          status={article.vectorStatus || 'pending'}
                          chunkCount={article.chunkCount || 0}
                          error={article.vectorError}
                        />
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-500">
                        {article.views}
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-500 whitespace-nowrap">
                        {formatDate(article.updatedAt)}
                      </td>
                      <td className="px-6 py-4 text-right text-sm font-medium">
                        <div className="flex justify-end space-x-2">
                          {article.status === 'published' && (
                            <motion.button
                              whileHover={{ scale: 1.1 }}
                              whileTap={{ scale: 0.9 }}
                              onClick={() => handleVectorizeDocument(article.id, article.title)}
                              className="text-green-600 hover:text-green-900"
                              title="向量化"
                              disabled={vectorizationProgress.status === 'processing'}
                            >
                              <FaDatabase />
                            </motion.button>
                          )}
                          <motion.button
                            whileHover={{ scale: 1.1 }}
                            whileTap={{ scale: 0.9 }}
                            onClick={() => exportArticle(article)}
                            className="text-purple-600 hover:text-purple-900"
                            title="导出"
                          >
                            <FaDownload />
                          </motion.button>
                          <motion.button
                            whileHover={{ scale: 1.1 }}
                            whileTap={{ scale: 0.9 }}
                            onClick={() => openEditModal(article)}
                            className="text-blue-600 hover:text-blue-900"
                            title="编辑"
                          >
                            <FaEdit />
                          </motion.button>
                          <motion.button
                            whileHover={{ scale: 1.1 }}
                            whileTap={{ scale: 0.9 }}
                            onClick={() => handleDeleteArticle(article.id)}
                            className="text-red-600 hover:text-red-900"
                            title="删除"
                          >
                            <FaTrash />
                          </motion.button>
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={10} className="px-6 py-12 text-center">
                      <div className="text-gray-500">
                        <FaBook className="mx-auto h-12 w-12 text-gray-400 mb-3" />
                        <p>没有找到匹配的文章</p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* 添加/编辑文章模态框 */}
        {(isAddModalOpen || isEditModalOpen) && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4"
          >
            <motion.div
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              className="bg-white rounded-xl shadow-xl w-full max-w-2xl p-6 max-h-[90vh] overflow-y-auto relative"
            >
              <button
                type="button"
                onClick={() => {
                  setIsAddModalOpen(false);
                  setIsEditModalOpen(false);
                  resetForm();
                }}
                className="absolute top-4 right-4 text-gray-400 hover:text-gray-600 transition-colors"
              >
                <FaTimes className="h-5 w-5" />
              </button>
              
              <h3 className="text-lg font-semibold text-gray-900 mb-4 pr-8">
                {isAddModalOpen ? '添加新文章' : '编辑文章'}
              </h3>
              
              <form onSubmit={(e) => {
                e.preventDefault();
                if (isAddModalOpen) {
                  handleAddArticle();
                } else {
                  handleUpdateArticle();
                }
              }} className="space-y-4">
                <div>
                  <label htmlFor="title" className="block text-sm font-medium text-gray-700 mb-1">
                    标题 <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    id="title"
                    value={formData.title}
                    onChange={(e) => setFormData(prev => ({ ...prev, title: e.target.value }))}
                    className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    required
                  />
                </div>
                
                <div>
                  <label htmlFor="category" className="block text-sm font-medium text-gray-700 mb-1">
                    分类 <span className="text-red-500">*</span>
                  </label>
                  <select
                    id="category"
                    value={formData.category}
                    onChange={(e) => setFormData(prev => ({ ...prev, category: e.target.value }))}
                    className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  >
                    {availableCategories.map((category) => (
                      <option key={category} value={category}>
                        {category}
                      </option>
                    ))}
                  </select>
                </div>
                
                <div>
                  <label htmlFor="content" className="block text-sm font-medium text-gray-700 mb-1">
                    内容 <span className="text-red-500">*</span>
                  </label>
                  <textarea
                    id="content"
                    value={formData.content}
                    onChange={(e) => setFormData(prev => ({ ...prev, content: e.target.value }))}
                    rows={8}
                    className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    required
                  />
                </div>
                
                <div>
                  <label htmlFor="tags" className="block text-sm font-medium text-gray-700 mb-1">
                    标签
                  </label>
                  <div className="flex items-center space-x-2 mb-2">
                    <input
                      type="text"
                      id="tags"
                      value={tagInput}
                      onChange={(e) => setTagInput(e.target.value)}
                      onKeyPress={(e) => e.key === 'Enter' && (e.preventDefault(), handleAddTag())}
                      className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      placeholder="输入标签后按回车添加"
                    />
                    <button
                      type="button"
                      onClick={handleAddTag}
                      className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                    >
                      添加
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {formData.tags.map((tag, index) => (
                      <span key={index} className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-sm flex items-center whitespace-nowrap">
                        {tag}
                        <button
                          type="button"
                          onClick={() => handleRemoveTag(tag)}
                          className="ml-1 text-blue-600 hover:text-blue-800"
                        >
                          <FaTimes className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    状态
                  </label>
                  <div className="space-y-2">
                    <label className="flex items-center">
                      <input
                        type="radio"
                        value="draft"
                        checked={formData.status === 'draft'}
                        onChange={(e) => setFormData(prev => ({ ...prev, status: e.target.value as 'published' | 'draft' }))}
                        className="mr-2"
                      />
                      草稿
                    </label>
                    <label className="flex items-center">
                      <input
                        type="radio"
                        value="published"
                        checked={formData.status === 'published'}
                        onChange={(e) => setFormData(prev => ({ ...prev, status: e.target.value as 'published' | 'draft' }))}
                        className="mr-2"
                      />
                      发布
                    </label>
                  </div>
                </div>
                
                <div className="flex justify-end space-x-3 pt-4 border-t border-gray-200">
                  <button
                    type="button"
                    onClick={() => {
                      setIsAddModalOpen(false);
                      setIsEditModalOpen(false);
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
                    {isAddModalOpen ? '添加文章' : '更新文章'}
                  </button>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
        
        {/* 知识库设置模态框 */}
        {isSettingsModalOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4"
          >
            <motion.div
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              className="bg-white rounded-xl shadow-xl w-full max-w-2xl p-6 max-h-[90vh] overflow-y-auto"
            >
              <div className="flex items-center mb-4">
                <FaDatabase className="text-blue-600 text-xl mr-3" />
                <h3 className="text-lg font-semibold text-gray-900">
                  知识库设置
                </h3>
              </div>
              
              <form onSubmit={handleSaveSettings} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="vectorDbType" className="block text-sm font-medium text-gray-700 mb-1">
                      向量数据库类型
                    </label>
                    <select
                      id="vectorDbType"
                      value={vectorDbSettings.type}
                      onChange={(e) => setVectorDbSettings(prev => ({ 
                        ...prev, 
                        type: e.target.value as VectorDbType 
                      }))}
                      className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      disabled
                    >
                      <option value="pgvector">pgvector (PostgreSQL)</option>
                    </select>
                    <p className="mt-1 text-xs text-gray-500">系统现在使用 pgvector 作为向量数据库</p>
                  </div>
                  
                  <div>
                    <label htmlFor="embeddingModel" className="block text-sm font-medium text-gray-700 mb-1">
                      嵌入模型
                    </label>
                    <select
                      id="embeddingModel"
                      value={vectorDbSettings.embeddingModel}
                      onChange={(e) => {
                        const selectedModelName = e.target.value;
                        const selectedModel = embeddingModels.find(m => m.modelName === selectedModelName);
                        
                        console.log('[KB] embeddingModel changed:', selectedModelName, selectedModel);
                        
                        // 自动设置 API URL（如果找到匹配的模型）
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
                          embeddingApiUrl: apiUrl
                        }));
                      }}
                      className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      required
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
                    <p className="text-xs text-gray-500 mt-1">
                      支持 Ollama 或 OpenAI 兼容的嵌入模型
                      {embeddingModels.length > 0 && ` (共 ${embeddingModels.length} 个可用模型)`}
                    </p>
                    {vectorDbSettings.embeddingApiUrl && (
                      <p className="text-xs text-blue-600 mt-1">
                        API: {vectorDbSettings.embeddingApiUrl}
                      </p>
                    )}
                  </div>
                  
                  <div>
                    <label htmlFor="embeddingDimension" className="block text-sm font-medium text-gray-700 mb-1">
                      向量维度
                    </label>
                    <input
                      type="number"
                      id="embeddingDimension"
                      value={vectorDbSettings.embeddingDimension || 1536}
                      onChange={(e) => setVectorDbSettings(prev => ({ 
                        ...prev, 
                        embeddingDimension: parseInt(e.target.value) || 1536
                      }))}
                      className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      min="128"
                      max="4096"
                      placeholder="1536"
                    />
                    <p className="text-xs text-gray-500 mt-1">
                      向量的维度，需要与模型输出维度匹配
                    </p>
                  </div>
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="chunkSize" className="block text-sm font-medium text-gray-700 mb-1">
                      文本块大小
                    </label>
                    <input
                      type="number"
                      id="chunkSize"
                      value={vectorDbSettings.chunkSize}
                      onChange={(e) => setVectorDbSettings(prev => ({ 
                        ...prev, 
                        chunkSize: parseInt(e.target.value) 
                      }))}
                      className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      min="100"
                      max="4000"
                    />
                    <p className="text-xs text-gray-500 mt-1">每个文本块的字符数</p>
                  </div>
                  
                  <div>
                    <label htmlFor="chunkOverlap" className="block text-sm font-medium text-gray-700 mb-1">
                      文本块重叠大小
                    </label>
                    <input
                      type="number"
                      id="chunkOverlap"
                      value={vectorDbSettings.chunkOverlap}
                      onChange={(e) => setVectorDbSettings(prev => ({ 
                        ...prev, 
                        chunkOverlap: parseInt(e.target.value) 
                      }))}
                      className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      min="0"
                      max="1000"
                    />
                    <p className="text-xs text-gray-500 mt-1">相邻文本块的重叠字符数</p>
                  </div>
                </div>
                
                <div>
                  <label htmlFor="connectionString" className="block text-sm font-medium text-gray-700 mb-1">
                    数据库连接字符串
                  </label>
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
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    嵌入模型测试
                  </label>
                  <button
                    type="button"
                    onClick={handleTestConnection}
                    disabled={testingConnection || !vectorDbSettings.embeddingModel}
                    className="w-full px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center justify-center"
                  >
                    {testingConnection ? (
                      <>
                        <FaSpinner className="animate-spin mr-2" />
                        测试中...
                      </>
                    ) : (
                      <>
                        <FaPlug className="mr-2" />
                        测试嵌入模型连接
                      </>
                    )}
                  </button>
                  <p className="text-xs text-gray-500 mt-1">
                    测试所选嵌入模型是否可用
                  </p>
                </div>
                
                <div className="flex justify-end space-x-3 pt-4 border-t border-gray-200">
                  <button
                    type="button"
                    onClick={() => setIsSettingsModalOpen(false)}
                    className="px-4 py-2 border border-gray-300 rounded-lg font-medium text-gray-700 hover:bg-gray-50"
                  >
                    取消
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700"
                  >
                    保存设置
                  </button>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
        
        {/* 向量化进度模态框 */}
        <VectorizationProgressModal
          isOpen={showProgressModal}
          onClose={() => setShowProgressModal(false)}
          progress={vectorizationProgress}
          onCancel={cancelVectorization}
          onRetry={handleRetryFailedDocuments}
        />
            </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
};

export default KnowledgeBase;