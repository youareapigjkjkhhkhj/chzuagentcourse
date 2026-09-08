import { UserInfo } from '../contexts/authContext';

export const API_BASE_URL = 'http://localhost:5000/api';

// 存储JWT token
let authToken: string | null = localStorage.getItem('authToken');

// 设置token
export const setAuthToken = (token: string | null) => {
  authToken = token;
  if (token) {
    localStorage.setItem('authToken', token);
  } else {
    localStorage.removeItem('authToken');
  }
};

// 获取请求头
const getHeaders = () => {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  
  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }
  
  return headers;
};

// 通用API请求方法
const apiRequest = async (endpoint: string, options: RequestInit = {}) => {
  const url = `${API_BASE_URL}${endpoint}`;
  const config: RequestInit = {
    headers: getHeaders(),
    ...options,
  };

  try {
    const response = await fetch(url, config);
    
    // 处理204 No Content响应
    if (response.status === 204) {
      return { success: true };
    }
    
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.message || `HTTP error! status: ${response.status}`);
    }

    return data;
  } catch (error) {
    console.error('API request failed:', error);
    throw error;
  }
};

export const buildFileUrl = (path: string | null | undefined): string => {
  if (!path) return '';
  if (path.startsWith('http://') || path.startsWith('https://')) return path;
  const base = API_BASE_URL.replace(/\/api$/, '');
  return `${base}${path}`;
};

// 认证相关API
export const authAPI = {
  // 用户登录
  login: async (email: string, password: string) => {
    const response = await apiRequest('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username: email, password }),
    });

    // 保存token
    if (response && response.data && response.data.token) {
      setAuthToken(response.data.token);
    }

    return response;
  },

  // 用户注册
  register: async (userData: {
    username: string;
    email: string;
    password: string;
    name: string;
    role: 'doctor' | 'admin';
  }) => {
    return await apiRequest('/auth/register', {
      method: 'POST',
      body: JSON.stringify(userData),
    });
  },

  // 获取当前用户信息
  getCurrentUser: async () => {
    return await apiRequest('/auth/me');
  },

  // 更新个人信息
  updateProfile: async (userData: {
    name?: string;
    email?: string;
    username?: string;
  }) => {
    return await apiRequest('/auth/profile', {
      method: 'PUT',
      body: JSON.stringify(userData),
    });
  },

  // 修改密码
  changePassword: async (passwordData: {
    currentPassword: string;
    newPassword: string;
  }) => {
    return await apiRequest('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify(passwordData),
    });
  },

  // 登出
  logout: () => {
    setAuthToken(null);
  },
};

// 聊天记录相关API
export const chatHistoryAPI = {
  // 获取用户的聊天会话列表
  getSessions: async (params?: {
    page?: number;
    per_page?: number;
    search?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.append('page', params.page.toString());
    if (params?.per_page) searchParams.append('per_page', params.per_page.toString());
    if (params?.search) searchParams.append('search', params.search);
    
    const queryString = searchParams.toString();
    const url = `/chat/sessions${queryString ? '?' + queryString : ''}`;
    return await apiRequest(url);
  },

  // 获取单个聊天会话
  getSession: async (sessionId: string) => {
    return await apiRequest(`/chat/sessions/${sessionId}`);
  },

  // 创建新的聊天会话
  createSession: async (data?: {
    title?: string;
  }) => {
    return await apiRequest('/chat/sessions', {
      method: 'POST',
      body: JSON.stringify(data || {}),
    });
  },

  // 更新聊天会话
  updateSession: async (sessionId: string, data: {
    title?: string;
  }) => {
    return await apiRequest(`/chat/sessions/${sessionId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  // 删除聊天会话
  deleteSession: async (sessionId: string) => {
    return await apiRequest(`/chat/sessions/${sessionId}`, {
      method: 'DELETE',
    });
  },

  // 获取会话中的消息列表
  getMessages: async (sessionId: string, params?: {
    page?: number;
    per_page?: number;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.append('page', params.page.toString());
    if (params?.per_page) searchParams.append('per_page', params.per_page.toString());
    
    const queryString = searchParams.toString();
    const url = `/chat/sessions/${sessionId}/messages${queryString ? '?' + queryString : ''}`;
    return await apiRequest(url);
  },

  // 添加消息到会话
  addMessage: async (sessionId: string, data: {
    content: string;
    message_type?: 'user' | 'ai';
    source?: string;
  }) => {
    return await apiRequest(`/chat/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  // 删除消息
  deleteMessage: async (sessionId: string, messageId: string) => {
    return await apiRequest(`/chat/sessions/${sessionId}/messages/${messageId}`, {
      method: 'DELETE',
    });
  },

  // 获取用户聊天统计
  getChatStats: async () => {
    return await apiRequest('/chat/statistics');
  },

  // 导出会话
  exportSession: async (sessionId: string, format?: 'json' | 'txt' | 'csv') => {
    const url = `/chat/sessions/${sessionId}/export${format ? '?format=' + format : ''}`;
    
    try {
      const response = await fetch(`${API_BASE_URL}${url}`, {
        method: 'GET',
        headers: getHeaders(),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.message || `HTTP error! status: ${response.status}`);
      }

      // 获取文件名
      const contentDisposition = response.headers.get('content-disposition');
      let filename = `chat_session_${sessionId}.${format || 'json'}`;
      if (contentDisposition) {
        const filenameMatch = contentDisposition.match(/filename="(.+)"/);
        if (filenameMatch) {
          filename = filenameMatch[1];
        }
      }

      // 获取文件数据
      const blob = await response.blob();
      
      // 创建下载链接
      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(downloadUrl);

      return { success: true };
    } catch (error) {
      console.error('Export session failed:', error);
      throw error;
    }
  },
};

// 用户管理相关API
export const userAPI = {
  // 获取用户列表
  getUsers: async () => {
    return await apiRequest('/users/');
  },

  // 获取单个用户信息
  getUser: async (id: string) => {
    return await apiRequest(`/users/${id}`);
  },

  // 创建用户
  createUser: async (userData: {
    name: string;
    email: string;
    password: string;
    role: 'doctor' | 'admin';
  }) => {
    // 前端使用name字段，后端需要username，所以添加一个默认的username
    const username = userData.email.split('@')[0] + '_' + Date.now().toString().slice(-6);
    
    return await apiRequest('/users/', {
      method: 'POST',
      body: JSON.stringify({
        username: username,
        name: userData.name,
        email: userData.email,
        password: userData.password,
        role: userData.role
      }),
    });
  },

  // 更新用户信息
  updateUser: async (id: string, userData: {
    name?: string;
    email?: string;
    role?: 'doctor' | 'admin';
    password?: string;
  }) => {
    return await apiRequest(`/users/${id}`, {
      method: 'PUT',
      body: JSON.stringify(userData),
    });
  },

  // 删除用户
  deleteUser: async (id: string) => {
    return await apiRequest(`/users/${id}`, {
      method: 'DELETE',
    });
  },

  // 导出用户列表为Excel
  exportUsers: async (filters?: {
    search?: string;
    role?: string;
    is_active?: boolean;
  }) => {
    // 构建查询参数
    const params = new URLSearchParams();
    if (filters?.search) params.append('search', filters.search);
    if (filters?.role) params.append('role', filters.role);
    if (filters?.is_active !== undefined) params.append('is_active', filters.is_active.toString());
    
    const url = `${API_BASE_URL}/users/export${params.toString() ? '?' + params.toString() : ''}`;
    
    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: getHeaders(),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.message || `HTTP error! status: ${response.status}`);
      }

      // 获取文件名
      const contentDisposition = response.headers.get('content-disposition');
      let filename = '用户列表.xlsx';
      if (contentDisposition) {
        const filenameMatch = contentDisposition.match(/filename="(.+)"/);
        if (filenameMatch) {
          filename = filenameMatch[1];
        }
      }

      // 获取文件数据
      const blob = await response.blob();
      
      // 创建下载链接
      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(downloadUrl);

      return { success: true };
    } catch (error) {
      console.error('Export users failed:', error);
      throw error;
    }
  },
};

// 转换后端用户数据为前端格式
export const transformUser = (backendUser: any): UserInfo => {
  return {
    id: backendUser.id?.toString() || backendUser._id?.toString(),
    email: backendUser.email,
    name: backendUser.name,
    role: backendUser.role,
    lastLogin: backendUser.lastLogin,
  };
};

// 模型管理相关API
export const modelAPI = {
  // 获取所有模型
  getModels: async () => {
    return await apiRequest('/models/');
  },

  // 获取单个模型
  getModel: async (id: string) => {
    return await apiRequest(`/models/${id}`);
  },

  // 获取默认模型
  getDefaultModel: async () => {
    return await apiRequest('/models/default');
  },

  // 创建模型
  createModel: async (modelData: {
    name: string;
    provider: string;
    type: string;
    modelName: string;
    apiKey?: string;
    apiEndpoint?: string;
    temperature?: number;
    maxTokens?: number;
    topP?: number;
    systemPrompt?: string;
    description?: string;
    isDefault?: boolean;
  }) => {
    return await apiRequest('/models/', {
      method: 'POST',
      body: JSON.stringify(modelData),
    });
  },

  // 更新模型
  updateModel: async (id: string, modelData: {
    name?: string;
    provider?: string;
    type?: string;
    modelName?: string;
    apiKey?: string;
    apiEndpoint?: string;
    temperature?: number;
    maxTokens?: number;
    topP?: number;
    systemPrompt?: string;
    description?: string;
    isDefault?: boolean;
  }) => {
    return await apiRequest(`/models/${id}`, {
      method: 'PUT',
      body: JSON.stringify(modelData),
    });
  },

  // 删除模型
  deleteModel: async (id: string) => {
    return await apiRequest(`/models/${id}`, {
      method: 'DELETE',
    });
  },

  // 设置默认模型
  setDefaultModel: async (id: string) => {
    return await apiRequest(`/models/${id}/set-default`, {
      method: 'POST',
    });
  },

  // 测试模型连接
  testModel: async (id: string) => {
    return await apiRequest(`/models/${id}/test`, {
      method: 'POST',
    });
  },
};

// 知识库管理相关API
export const knowledgeAPI = {
  // 获取知识库文章列表
  getArticles: async (params?: {
    page?: number;
    per_page?: number;
    search?: string;
    category?: string;
    status?: string;
    sort_by?: 'title' | 'createdAt' | 'views';
    sort_order?: 'asc' | 'desc';
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.append('page', params.page.toString());
    if (params?.per_page) searchParams.append('per_page', params.per_page.toString());
    if (params?.search) searchParams.append('search', params.search);
    if (params?.category) searchParams.append('category', params.category);
    if (params?.status) searchParams.append('status', params.status);
    if (params?.sort_by) searchParams.append('sort_by', params.sort_by);
    if (params?.sort_order) searchParams.append('sort_order', params.sort_order);
    
    const queryString = searchParams.toString();
    const url = `/knowledge/articles${queryString ? '?' + queryString : ''}`;
    console.debug('[knowledgeAPI.getArticles] GET', url);
    const res = await apiRequest(url);
    const count = res?.data?.articles ? res.data.articles.length : (Array.isArray(res?.articles) ? res.articles.length : 'n/a');
    console.debug('[knowledgeAPI.getArticles] result success=', !!res?.success, 'articles=', count);
    return res;
  },

  // 获取单个知识库文章
  getArticle: async (articleId: string) => {
    return await apiRequest(`/knowledge/articles/${articleId}`);
  },

  // 创建知识库文章
  createArticle: async (articleData: {
    title: string;
    content: string;
    category: string;
    tags?: string[];
    status?: 'draft' | 'published';
    author?: string;
  }) => {
    console.debug('[knowledgeAPI.createArticle] POST /knowledge/articles payload', {
      title: articleData.title,
      category: articleData.category,
      status: articleData.status,
      tagsCount: articleData.tags?.length || 0,
      author: articleData.author,
    });
    const res = await apiRequest('/knowledge/articles', {
      method: 'POST',
      body: JSON.stringify(articleData),
    });
    console.debug('[knowledgeAPI.createArticle] result success=', !!res?.success, 'id=', res?.data?.article?.id);
    return res;
  },

  // 更新知识库文章
  updateArticle: async (articleId: string, articleData: {
    title?: string;
    content?: string;
    category?: string;
    tags?: string[];
    status?: 'draft' | 'published';
    author?: string;
  }) => {
    return await apiRequest(`/knowledge/articles/${articleId}`, {
      method: 'PUT',
      body: JSON.stringify(articleData),
    });
  },

  // 删除知识库文章
  deleteArticle: async (articleId: string) => {
    return await apiRequest(`/knowledge/articles/${articleId}`, {
      method: 'DELETE',
    });
  },

  // 批量操作文章
  batchOperate: async (operation: 'delete' | 'publish' | 'draft', articleIds: string[]) => {
    return await apiRequest('/knowledge/articles/batch', {
      method: 'POST',
      body: JSON.stringify({
        operation,
        article_ids: articleIds,
      }),
    });
  },

  // 获取所有分类
  getCategories: async () => {
    return await apiRequest('/knowledge/categories');
  },

  // 搜索知识库文章
  searchArticles: async (query: string, params?: {
    limit?: number;
    searchType?: 'hybrid' | 'vector' | 'sql';
    similarityThreshold?: number;
  }) => {
    // 使用新的搜索API端点
    return await apiRequest('/kb/search', {
      method: 'POST',
      body: JSON.stringify({
        query,
        // 不指定limit，让后端使用知识库设置中的默认值
        searchType: params?.searchType || 'hybrid',
        similarityThreshold: params?.similarityThreshold || 0.3, // 设置默认相似度阈值为0.3
        highlight: true
      }),
    });
  },

  // 获取知识库统计信息
  getStats: async () => {
    return await apiRequest('/knowledge/stats');
  },

  // 获取知识库设置
  getSettings: async () => {
    console.debug('[knowledgeAPI.getSettings] GET /settings/knowledge-base');
    const res = await apiRequest('/settings/knowledge-base');
    console.debug('[knowledgeAPI.getSettings] result success=', !!res?.success, 'settings=', res?.data);
    return res;
  },

  // 更新知识库设置
  updateSettings: async (settings: {
    vectorDbType?: string;
    embeddingModel?: string;
    embeddingApiUrl?: string;
    embeddingDimension?: number;
    chunkSize?: number;
    chunkOverlap?: number;
    connectionString?: string;
    similarityThreshold?: number;
    maxSearchResults?: number;
  }) => {
    const payload = {
      // 兼容前端 state 使用的 `type` 与后端期望的 `vectorDbType`
      vectorDbType: (settings as any).vectorDbType ?? (settings as any).type ?? 'pgvector',
      embeddingModel: settings.embeddingModel,
      embeddingApiUrl: settings.embeddingApiUrl,
      embeddingDimension: settings.embeddingDimension,
      chunkSize: settings.chunkSize,
      chunkOverlap: settings.chunkOverlap,
      connectionString: settings.connectionString,
      similarityThreshold: settings.similarityThreshold,
      maxSearchResults: settings.maxSearchResults,
    };
    console.debug('[knowledgeAPI.updateSettings] PUT /settings/knowledge-base payload', payload);
    const res = await apiRequest('/settings/knowledge-base', {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
    console.debug('[knowledgeAPI.updateSettings] result success=', !!res?.success);
    return res;
  },

  // 测试嵌入模型连接
  testEmbedding: async (params?: {
    embeddingModel?: string;
    embeddingApiUrl?: string;
    testText?: string;
  }) => {
    console.debug('[knowledgeAPI.testEmbedding] POST /settings/test-embedding', params);
    const res = await apiRequest('/settings/test-embedding', {
      method: 'POST',
      body: JSON.stringify(params || {}),
    });
    console.debug('[knowledgeAPI.testEmbedding] result success=', !!res?.success, 'available=', res?.data?.available);
    return res;
  },
};

// 知识库设置 API（pgvector）
export const kbSettingsAPI = {
  // 获取知识库设置
  getSettings: async () => {
    return await apiRequest('/settings/knowledge-base');
  },

  // 更新知识库设置
  updateSettings: async (settings: {
    vectorDbType?: string;
    embeddingModel?: string;
    embeddingDimension?: number;
    chunkSize?: number;
    chunkOverlap?: number;
    similarityThreshold?: number;
    maxSearchResults?: number;
  }) => {
    return await apiRequest('/settings/knowledge-base', {
      method: 'PUT',
      body: JSON.stringify(settings),
    });
  },

  // 测试嵌入模型连接
  testEmbedding: async (params?: {
    embeddingModel?: string;
    embeddingApiUrl?: string;
    testText?: string;
  }) => {
    return await apiRequest('/settings/test-embedding', {
      method: 'POST',
      body: JSON.stringify(params || {}),
    });
  },
};

// 知识库管理 API（新的 pgvector 实现）
export const knowledgeBaseAPI = {
  // 获取知识库列表
  getKnowledgeBases: async (params?: {
    page?: number;
    per_page?: number;
    search?: string;
    status?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.append('page', params.page.toString());
    if (params?.per_page) searchParams.append('per_page', params.per_page.toString());
    if (params?.search) searchParams.append('search', params.search);
    if (params?.status) searchParams.append('status', params.status);
    
    const queryString = searchParams.toString();
    const url = `/kb${queryString ? '?' + queryString : ''}`;
    return await apiRequest(url);
  },

  // 获取单个知识库
  getKnowledgeBase: async (kbId: string) => {
    return await apiRequest(`/kb/${kbId}`);
  },

  // 创建知识库
  createKnowledgeBase: async (data: {
    name: string;
    description?: string;
    embeddingModel?: string;
    status?: 'active' | 'archived';
  }) => {
    return await apiRequest('/kb', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  // 更新知识库
  updateKnowledgeBase: async (kbId: string, data: {
    name?: string;
    description?: string;
    embeddingModel?: string;
    status?: 'active' | 'archived';
  }) => {
    return await apiRequest(`/kb/${kbId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  // 删除知识库
  deleteKnowledgeBase: async (kbId: string) => {
    return await apiRequest(`/kb/${kbId}`, {
      method: 'DELETE',
    });
  },

  // 获取知识库统计信息
  getKnowledgeBaseStats: async (kbId: string) => {
    return await apiRequest(`/kb/${kbId}/stats`);
  },

  // 向量化知识库中的所有文档
  vectorizeKnowledgeBase: async (kbId: string, force = false) => {
    return await apiRequest(`/kb/${kbId}/sync-vectors`, {
      method: 'POST',
      body: JSON.stringify({ force }),
    });
  },
};

// 文档管理 API
export const documentAPI = {
  // 获取文档列表
  getDocuments: async (kbId: string, params?: {
    page?: number;
    per_page?: number;
    search?: string;
    status?: string;
    category?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.append('page', params.page.toString());
    if (params?.per_page) searchParams.append('per_page', params.per_page.toString());
    if (params?.search) searchParams.append('search', params.search);
    if (params?.status) searchParams.append('status', params.status);
    if (params?.category) searchParams.append('category', params.category);
    
    const queryString = searchParams.toString();
    const url = `/kb/${kbId}/documents${queryString ? '?' + queryString : ''}`;
    return await apiRequest(url);
  },

  // 获取单个文档
  getDocument: async (kbId: string, docId: string) => {
    return await apiRequest(`/kb/${kbId}/documents/${docId}`);
  },

  // 创建文档
  createDocument: async (kbId: string, data: {
    title: string;
    content: string;
    category?: string;
    tags?: string[];
    status?: 'draft' | 'published';
  }) => {
    return await apiRequest(`/kb/${kbId}/documents`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  // 更新文档
  updateDocument: async (kbId: string, docId: string, data: {
    title?: string;
    content?: string;
    category?: string;
    tags?: string[];
    status?: 'draft' | 'published';
  }) => {
    return await apiRequest(`/kb/${kbId}/documents/${docId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  // 删除文档
  deleteDocument: async (kbId: string, docId: string) => {
    return await apiRequest(`/kb/${kbId}/documents/${docId}`, {
      method: 'DELETE',
    });
  },

  // 上传单文件
  uploadFile: async (kbId: string, file: File, data: {
    title?: string;
    category?: string;
    tags?: string[];
    status?: 'draft' | 'published';
  }, onProgress?: (progress: number) => void) => {
    const formData = new FormData();
    formData.append('file', file);
    if (data.title) formData.append('title', data.title);
    if (data.category) formData.append('category', data.category);
    if (data.tags) formData.append('tags', JSON.stringify(data.tags));
    if (data.status) formData.append('status', data.status);

    const url = `${API_BASE_URL}/kb/${kbId}/documents/upload`;
    
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      
      // 监听上传进度
      if (onProgress) {
        xhr.upload.addEventListener('progress', (event) => {
          if (event.lengthComputable) {
            const progress = Math.round((event.loaded / event.total) * 100);
            onProgress(progress);
          }
        });
      }
      
      // 监听响应
      xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            const response = JSON.parse(xhr.responseText);
            resolve(response);
          } catch (error) {
            reject(new Error('解析响应失败'));
          }
        } else {
          try {
            const errorResponse = JSON.parse(xhr.responseText);
            reject(new Error(errorResponse.message || `HTTP error! status: ${xhr.status}`));
          } catch {
            reject(new Error(`HTTP error! status: ${xhr.status}`));
          }
        }
      });
      
      xhr.addEventListener('error', () => {
        reject(new Error('网络错误'));
      });
      
      // 打开请求
      xhr.open('POST', url);
      
      // 设置请求头
      if (authToken) {
        xhr.setRequestHeader('Authorization', `Bearer ${authToken}`);
      }
      
      // 发送请求
      xhr.send(formData);
    });
  },

  // 上传 ZIP 文件
  uploadZip: async (kbId: string, file: File, data: {
    title?: string;
    category?: string;
    tags?: string[];
    status?: 'draft' | 'published';
  }, onProgress?: (progress: number) => void) => {
    const formData = new FormData();
    formData.append('file', file);
    if (data.title) formData.append('title', data.title);
    if (data.category) formData.append('category', data.category);
    if (data.tags) formData.append('tags', JSON.stringify(data.tags));
    if (data.status) formData.append('status', data.status);

    const url = `${API_BASE_URL}/kb/${kbId}/documents/upload-zip`;
    
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      
      // 监听上传进度
      if (onProgress) {
        xhr.upload.addEventListener('progress', (event) => {
          if (event.lengthComputable) {
            const progress = Math.round((event.loaded / event.total) * 100);
            onProgress(progress);
          }
        });
      }
      
      // 监听响应
      xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            const response = JSON.parse(xhr.responseText);
            resolve(response);
          } catch (error) {
            reject(new Error('解析响应失败'));
          }
        } else {
          try {
            const errorResponse = JSON.parse(xhr.responseText);
            reject(new Error(errorResponse.message || `HTTP error! status: ${xhr.status}`));
          } catch {
            reject(new Error(`HTTP error! status: ${xhr.status}`));
          }
        }
      });
      
      xhr.addEventListener('error', () => {
        reject(new Error('网络错误'));
      });
      
      // 打开请求
      xhr.open('POST', url);
      
      // 设置请求头
      if (authToken) {
        xhr.setRequestHeader('Authorization', `Bearer ${authToken}`);
      }
      
      // 发送请求
      xhr.send(formData);
    });
  },

  // 批量操作
  batchOperate: async (kbId: string, operation: 'delete' | 'publish' | 'draft' | 'sync-vectors', documentIds: string[]) => {
    return await apiRequest(`/kb/${kbId}/documents/batch`, {
      method: 'POST',
      body: JSON.stringify({
        operation,
        documentIds,
      }),
    });
  },

  // 向量化文档
  vectorizeDocument: async (kbId: string, docId: string, force: boolean = false) => {
    return await apiRequest(`/kb/${kbId}/documents/${docId}/vectorize`, {
      method: 'POST',
      body: JSON.stringify({ force }),
    });
  },

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

  // 在知识库内搜索
  searchInKb: async (kbId: string, params: {
    query: string;
    searchType?: 'hybrid' | 'vector' | 'sql';
    limit?: number;
    similarityThreshold?: number;
    highlight?: boolean;
  }) => {
    return await apiRequest(`/kb/${kbId}/search`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  // 全局搜索（跨知识库）
  searchAllKbs: async (params: {
    query: string;
    searchType?: 'hybrid' | 'vector' | 'sql';
    limit?: number;
    similarityThreshold?: number;
    highlight?: boolean;
    kbIds?: string[];
  }) => {
    return await apiRequest('/kb/search', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },
};

// 向量化相关API
export const vectorizationAPI = {
  /**
   * 单文档向量化
   * @param kbId 知识库ID
   * @param docId 文档ID
   * @param options 向量化选项
   * @returns 向量化结果
   */
  vectorizeDocument: async (
    kbId: string,
    docId: string,
    options?: {
      force?: boolean;
      chunkSize?: number;
      chunkOverlap?: number;
    }
  ) => {
    try {
      const response = await apiRequest(`/kb/${kbId}/documents/${docId}/vectorize`, {
        method: 'POST',
        body: JSON.stringify(options || {}),
      });
      return response;
    } catch (error) {
      console.error('Vectorize document failed:', error);
      throw error;
    }
  },

  /**
   * 批量向量化
   * @param kbId 知识库ID
   * @param options 批量向量化选项
   * @returns 批量向量化结果
   */
  syncVectors: async (
    kbId: string,
    options?: {
      documentIds?: string[];
      force?: boolean;
      chunkSize?: number;
      chunkOverlap?: number;
    }
  ) => {
    try {
      const response = await apiRequest(`/kb/${kbId}/sync-vectors`, {
        method: 'POST',
        body: JSON.stringify(options || {}),
      });
      return response;
    } catch (error) {
      console.error('Sync vectors failed:', error);
      throw error;
    }
  },
};

// 转换后端知识库数据为前端格式
export const transformKnowledgeArticle = (backendArticle: any) => {
  // 规范化 tags：兼容后端可能返回的字符串或数组
  let normalizedTags: string[] = [];
  const rawTags = backendArticle?.tags;
  if (Array.isArray(rawTags)) {
    normalizedTags = rawTags;
  } else if (typeof rawTags === 'string') {
    try {
      const parsed = JSON.parse(rawTags);
      if (Array.isArray(parsed)) {
        normalizedTags = parsed;
      } else if (typeof parsed === 'string') {
        normalizedTags = parsed.split(',').map(t => t.trim()).filter(Boolean);
      } else {
        normalizedTags = [];
      }
    } catch {
      normalizedTags = rawTags.split(',').map(t => t.trim()).filter(Boolean);
    }
  } else {
    normalizedTags = [];
  }

  // 兼容大小写命名的时间字段
  const createdAt = backendArticle.createdAt || backendArticle.created_at || '';
  const updatedAt = backendArticle.updatedAt || backendArticle.updated_at || '';

  // 兼容搜索结果中的 article_id 字段
  const id = backendArticle.id || backendArticle.article_id;

  // 兼容向量化状态字段
  const vectorStatus = backendArticle.vectorStatus || backendArticle.vector_status || 'pending';
  const chunkCount = backendArticle.chunkCount ?? backendArticle.chunk_count ?? 0;
  const vectorError = backendArticle.vectorError || backendArticle.vector_error || undefined;

  return {
    id,
    title: backendArticle.title,
    content: backendArticle.content,
    category: backendArticle.category,
    tags: normalizedTags,
    author: backendArticle.author,
    status: backendArticle.status || 'draft',
    views: backendArticle.views ?? 0,
    createdAt,
    updatedAt,
    chunkCount,
    vectorStatus,
    vectorError,
  };
};

// 聊天相关API
export const chatAPI = {
  // 获取可用的对话模型列表
  getModels: async () => {
    return await apiRequest('/chat/models');
  },

  // 获取可用的知识库列表
  getKnowledgeBases: async () => {
    return await apiRequest('/chat/knowledge-bases');
  },

  // 发送聊天消息
  sendMessage: async (params: {
    message: string;
    modelId?: string;
    knowledgeBaseId?: string;
    useKnowledgeBase?: boolean;
  }) => {
    return await apiRequest('/chat/send', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  // 发送聊天消息（流式响应）
  sendMessageStream: (params: {
    message: string;
    modelId?: string;
    knowledgeBaseId?: string;
    useKnowledgeBase?: boolean;
  }, callbacks: {
    onStart?: (data: any) => void;
    onMessage?: (content: string) => void;
    onEnd?: () => void;
    onError?: (error: any) => void;
  }) => {
    const token = localStorage.getItem('authToken');
    if (!token) {
      callbacks.onError?.(new Error('未登录'));
      return () => {};
    }

    // 由于EventSource不支持自定义请求头，我们需要使用fetch来处理
    const controller = new AbortController();
    const signal = controller.signal;

    // 标记请求是否已完成
    let isCompleted = false;

    fetch(`${API_BASE_URL}/chat/send-stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify(params),
      signal
    })
    .then(response => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      
      if (!reader) {
        throw new Error('无法获取响应流');
      }
      
      let buffer = '';
      
      function processText(text: string) {
        buffer += text;
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6);
            if (dataStr.trim() === '[DONE]') {
              isCompleted = true;
              callbacks.onEnd?.();
              return;
            }
            
            try {
              const data = JSON.parse(dataStr);
              
              if (data.type === 'start') {
                callbacks.onStart?.(data);
              } else if (data.type === 'message') {
                callbacks.onMessage?.(data.content);
              } else if (data.type === 'end') {
                isCompleted = true;
                callbacks.onEnd?.();
              } else if (data.type === 'error') {
                isCompleted = true;
                callbacks.onError?.(new Error(data.message));
              }
            } catch (e) {
              console.error('解析SSE数据失败:', e);
            }
          }
        }
      }
      
      function read() {
        reader.read().then(({ done, value }) => {
          if (done) {
            if (buffer) processText('\n');
            if (!isCompleted) {
              isCompleted = true;
              callbacks.onEnd?.();
            }
            return;
          }
          
          const text = decoder.decode(value, { stream: true });
          processText(text);
          read();
        }).catch(error => {
          // 如果是AbortError且请求已完成，不触发错误回调
          if (error.name === 'AbortError' && isCompleted) {
            return;
          }
          // 如果是AbortError但请求未完成，可能是用户主动取消，不触发错误回调
          if (error.name === 'AbortError') {
            return;
          }
          isCompleted = true;
          callbacks.onError?.(error);
        });
      }
      
      read();
    })
    .catch(error => {
      // 如果是AbortError且请求已完成，不触发错误回调
      if (error.name === 'AbortError' && isCompleted) {
        return;
      }
      // 如果是AbortError但请求未完成，可能是用户主动取消，不触发错误回调
      if (error.name === 'AbortError') {
        return;
      }
      isCompleted = true;
      callbacks.onError?.(error);
    });
    
    // 返回一个可以取消请求的函数
    return () => {
      if (!isCompleted) {
        controller.abort();
      }
    };
  },
};

// 图像分析相关API
export const imageAnalysisAPI = {
  // 获取可用模型列表
  getAvailableModels: async () => {
    return await apiRequest('/analysis/models');
  },

  // 开始图像分析
  startAnalysis: async (formData: FormData) => {

    const url = `${API_BASE_URL}/analysis/start`;
    
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      
      // 监听响应
      xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            const response = JSON.parse(xhr.responseText);
            resolve(response);
          } catch (error) {
            reject(new Error('解析响应失败'));
          }
        } else {
          try {
            const errorResponse = JSON.parse(xhr.responseText);
            reject(new Error(errorResponse.message || `HTTP error! status: ${xhr.status}`));
          } catch {
            reject(new Error(`HTTP error! status: ${xhr.status}`));
          }
        }
      });
      
      xhr.addEventListener('error', () => {
        reject(new Error('网络错误'));
      });
      
      // 打开请求
      xhr.open('POST', url);
      
      // 设置请求头
      if (authToken) {
        xhr.setRequestHeader('Authorization', `Bearer ${authToken}`);
      }
      
      // 发送请求
      xhr.send(formData);
    });
  },

  // 获取分析结果
  getAnalysisResults: async (analysisId: string) => {
    return await apiRequest(`/analysis/${analysisId}/results`);
  },

  // 获取分析状态
  getAnalysisStatus: async (analysisId: string) => {
    return await apiRequest(`/analysis/${analysisId}/status`);
  },

  // 取消分析
  cancelAnalysis: async (analysisId: string) => {
    return await apiRequest(`/analysis/${analysisId}/cancel`, {
      method: 'POST',
    });
  },

  // 获取分析历史记录
  getAnalysisHistory: async (params?: {
    page?: number;
    per_page?: number;
    patient_id?: string;
    date_from?: string;
    date_to?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.append('page', params.page.toString());
    if (params?.per_page) searchParams.append('per_page', params.per_page.toString());
    if (params?.patient_id) searchParams.append('patient_id', params.patient_id);
    if (params?.date_from) searchParams.append('date_from', params.date_from);
    if (params?.date_to) searchParams.append('date_to', params.date_to);
    
    const queryString = searchParams.toString();
    const url = `/analysis/history${queryString ? '?' + queryString : ''}`;
    return await apiRequest(url);
  },

  // 导出分析报告
  exportAnalysisReport: async (analysisId: string, format?: 'pdf' | 'json' | 'csv') => {
    const url = `${API_BASE_URL}/analysis/${analysisId}/export${format ? '?format=' + format : ''}`;
    
    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: getHeaders(),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.message || `HTTP error! status: ${response.status}`);
      }

      // 获取文件名
      const contentDisposition = response.headers.get('content-disposition');
      let filename = `analysis_report_${analysisId}.${format || 'pdf'}`;
      if (contentDisposition) {
        const filenameMatch = contentDisposition.match(/filename="(.+)"/);
        if (filenameMatch) {
          filename = filenameMatch[1];
        }
      }

      // 获取文件数据
      const blob = await response.blob();
      
      // 创建下载链接
      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(downloadUrl);

      return { success: true };
    } catch (error) {
      console.error('Export analysis report failed:', error);
      throw error;
    }
  },

  // 删除分析记录
  deleteAnalysis: async (analysisId: string) => {
    return await apiRequest(`/analysis/${analysisId}`, {
      method: 'DELETE',
    });
  },

  // 获取分析统计信息
  getAnalysisStats: async (params?: {
    date_from?: string;
    date_to?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.date_from) searchParams.append('date_from', params.date_from);
    if (params?.date_to) searchParams.append('date_to', params.date_to);
    
    const queryString = searchParams.toString();
    const url = `/analysis/stats${queryString ? '?' + queryString : ''}`;
    return await apiRequest(url);
  },

  // 获取统计信息（Dashboard使用）
  getAnalysisStatsForDashboard: async () => {
    return await apiRequest('/analysis/stats');
  },
};

// 诊断报告相关API
export const reportsAPI = {
  // 创建诊断报告
  createReport: async (reportData: {
    analysis_id: string;
    patient_id: string;
    patient_name?: string;
    patient_age?: number;
    patient_gender?: string;
    ensemble_diagnosis_level: number;
    ensemble_confidence: number;
    analysis_results?: any[];
    model_predictions?: any[];
    clinical_summary?: string;
    features_detected?: any[];
    primary_recommendations?: string[];
    follow_up_plan?: string;
    lifestyle_advice?: string[];
    monitoring_schedule?: string;
  }) => {
    return await apiRequest('/reports', {
      method: 'POST',
      body: JSON.stringify(reportData),
    });
  },

  // 获取报告列表
  getReports: async (params?: {
    page?: number;
    per_page?: number;
    patient_id?: string;
    date_from?: string;
    date_to?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.append('page', params.page.toString());
    if (params?.per_page) searchParams.append('per_page', params.per_page.toString());
    if (params?.patient_id) searchParams.append('patient_id', params.patient_id);
    if (params?.date_from) searchParams.append('date_from', params.date_from);
    if (params?.date_to) searchParams.append('date_to', params.date_to);
    
    const queryString = searchParams.toString();
    const url = `/reports${queryString ? '?' + queryString : ''}`;
    return await apiRequest(url);
  },

  // 获取报告详情
  getReportDetail: async (reportId: string) => {
    return await apiRequest(`/reports/${reportId}`);
  },

  // 更新报告
  updateReport: async (
    reportId: string,
    reportData: {
      patient_name?: string;
      patient_age?: number;
      patient_gender?: string;
      clinical_summary?: string;
      recommendations?: {
        primary_recommendations?: string[];
        follow_up_plan?: string;
        lifestyle_advice?: string[];
        monitoring_schedule?: string;
      };
      follow_up_plan?: string;
    }
  ) => {
    return await apiRequest(`/reports/${reportId}`, {
      method: 'PUT',
      body: JSON.stringify(reportData),
    });
  },

  // 导出报告
  exportReport: async (reportId: string, format?: 'pdf' | 'json') => {
    const url = `${API_BASE_URL}/reports/export/${reportId}${format ? '?format=' + format : ''}`;
    
    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: getHeaders(),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.message || `HTTP error! status: ${response.status}`);
      }

      const data = await response.json();

      if (!data.success) {
        throw new Error(data.message || 'Export failed');
      }

      // 如果是PDF格式，返回HTML内容
      if (format === 'pdf') {
        return {
          success: true,
          data: data.data,
          message: data.message
        };
      } else {
        // 获取文件名
        const contentDisposition = response.headers.get('content-disposition');
        let filename = `diagnosis_report_${reportId}.${format || 'json'}`;
        if (contentDisposition) {
          const filenameMatch = contentDisposition.match(/filename="(.+)"/);
          if (filenameMatch) {
            filename = filenameMatch[1];
          }
        }

        // 获取文件数据
        const blob = new Blob([JSON.stringify(data.data, null, 2)], { type: 'application/json' });
        
        // 创建下载链接
        const downloadUrl = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        window.URL.revokeObjectURL(downloadUrl);

        return { success: true };
      }
    } catch (error) {
      console.error('Export report failed:', error);
      throw error;
    }
  },

  // 批量导出报告
  exportReports: async (reportIds: string[], format?: 'pdf' | 'excel') => {
    return await apiRequest('/reports/export', {
      method: 'POST',
      body: JSON.stringify({
        report_ids: reportIds,
        format: format || 'pdf'
      }),
    });
  },
};

// 转换后端图像分析数据为前端格式
export const transformImageAnalysis = (backendAnalysis: any) => {
  return {
    id: backendAnalysis.id,
    patient_id: backendAnalysis.patient_id,
    patient_name: backendAnalysis.patient_name,
    image_url: backendAnalysis.image_url,
    status: backendAnalysis.status,
    model_type: backendAnalysis.model_type,
    analysis_type: backendAnalysis.analysis_type,
    result: backendAnalysis.result,
    recommendations: backendAnalysis.recommendations,
    created_at: backendAnalysis.created_at,
    updated_at: backendAnalysis.updated_at,
    completed_at: backendAnalysis.completed_at,
  };
};
