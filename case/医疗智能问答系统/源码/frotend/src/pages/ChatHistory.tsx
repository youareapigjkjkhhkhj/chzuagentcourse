import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { chatHistoryAPI } from '../services/api';
import Navbar from '@/components/Navbar';
import Sidebar from '@/components/Sidebar';
import { motion } from 'framer-motion';
import axios from 'axios';

// 扩展chatHistoryAPI以包含词频功能
const extendedChatHistoryAPI = {
  ...chatHistoryAPI,
  getWordFrequencies: async () => {
    // 这里应该调用实际的API
    return {
      success: true,
      data: [
        { word: '青光眼', count: 15 },
        { word: '白内障', count: 12 },
        { word: '糖尿病', count: 10 },
        { word: '视网膜', count: 9 },
        { word: '症状', count: 8 },
        { word: '治疗', count: 7 },
        { word: '手术', count: 6 },
        { word: '眼压', count: 5 },
        { word: '视力', count: 5 },
        { word: '预防', count: 4 },
        { word: '检查', count: 4 },
        { word: '药物', count: 3 },
        { word: '康复', count: 3 },
        { word: '护理', count: 2 },
        { word: '饮食', count: 2 },
      ],
    };
  },
};

// 格式化时间函数
const formatTimeAgo = (dateString: string) => {
  const date = new Date(dateString);
  const now = new Date();
  const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);
  
  if (diffInSeconds < 60) {
    return "刚刚";
  } else if (diffInSeconds < 3600) {
    const minutes = Math.floor(diffInSeconds / 60);
    return `${minutes}分钟前`;
  } else if (diffInSeconds < 86400) {
    const hours = Math.floor(diffInSeconds / 3600);
    return `${hours}小时前`;
  } else if (diffInSeconds < 2592000) {
    const days = Math.floor(diffInSeconds / 86400);
    return `${days}天前`;
  } else {
    return date.toLocaleDateString('zh-CN');
  }
};

interface ChatSession {
  id: string;
  title: string;
  userId: number;
  modelId: string;
  knowledgeBaseId: string;
  isActive: boolean;
  messageCount: number;
  lastMessage?: string;
  createdAt: string;
  updatedAt: string;
}

interface ChatMessage {
  id: string;
  sessionId: string;
  content: string;
  role: 'user' | 'assistant';
  messageType: string;
  tokens: number;
  modelResponseTime: number;
  fromKnowledgeBase: boolean;
  sources?: any[];
  timestamp: string;
}

interface ChatStats {
  totalSessions: number;
  totalMessages: number;
  totalTokens: number;
  avgResponseTime: number;
  kbUsageRate: number;
}

interface WordFrequency {
  word: string;
  count: number;
}

const ChatHistory: React.FC = () => {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [selectedSession, setSelectedSession] = useState<ChatSession | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [stats, setStats] = useState<ChatStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [showStats, setShowStats] = useState(false);
  const [wordFrequencies, setWordFrequencies] = useState<WordFrequency[]>([]);
  const [showWordCloud, setShowWordCloud] = useState(false);

  // 加载聊天会话列表
  const loadSessions = async () => {
    try {
      setLoading(true);
      const response = await chatHistoryAPI.getSessions();
      if (response.success) {
        setSessions(response.data || []);
      } else {
        toast.error(response.message || '获取聊天会话失败');
      }
    } catch (error) {
      console.error('加载聊天会话失败:', error);
      toast.error('加载聊天会话失败');
    } finally {
      setLoading(false);
    }
  };

  // 加载统计数据
  const loadStats = async () => {
    try {
      const response = await chatHistoryAPI.getChatStats();
      if (response.success) {
        setStats(response.data);
      } else {
        toast.error(response.message || '获取统计数据失败');
      }
    } catch (error) {
      console.error('加载统计数据失败:', error);
      toast.error('加载统计数据失败');
    }
  };

  // 加载词云数据
  const loadWordFrequencies = async () => {
    try {
      const response = await extendedChatHistoryAPI.getWordFrequencies();
      if (response.success) {
        setWordFrequencies(response.data || []);
      } else {
        toast.error(response.message || '获取词频数据失败');
      }
    } catch (error) {
      console.error('加载词频数据失败:', error);
      toast.error('加载词频数据失败');
    }
  };

  // 加载会话消息
  const loadMessages = async (sessionId: string) => {
    try {
      setLoadingMessages(true);
      const response = await chatHistoryAPI.getMessages(sessionId);
      if (response.success) {
        setMessages(response.data || []);
      } else {
        toast.error(response.message || '获取消息失败');
      }
    } catch (error) {
      console.error('加载消息失败:', error);
      toast.error('加载消息失败');
    } finally {
      setLoadingMessages(false);
    }
  };

  // 创建新会话
  const createNewSession = async () => {
    try {
      const response = await chatHistoryAPI.createSession({
        title: `新会话 ${new Date().toLocaleString()}`
      });
      if (response.success) {
        toast.success('创建新会话成功');
        loadSessions();
      } else {
        toast.error(response.message || '创建会话失败');
      }
    } catch (error) {
      console.error('创建会话失败:', error);
      toast.error('创建会话失败');
    }
  };

  // 删除会话
  const deleteSession = async (sessionId: string) => {
    if (!window.confirm('确定要删除这个会话吗？此操作不可撤销。')) {
      return;
    }

    try {
      const response = await chatHistoryAPI.deleteSession(sessionId);
      if (response.success) {
        toast.success('删除会话成功');
        if (selectedSession?.id === sessionId) {
          setSelectedSession(null);
          setMessages([]);
        }
        loadSessions();
      } else {
        toast.error(response.message || '删除会话失败');
      }
    } catch (error) {
      console.error('删除会话失败:', error);
      toast.error('删除会话失败');
    }
  };

  // 导出会话
  const exportSession = async (sessionId: string, format: 'json' | 'txt' = 'json') => {
    try {
      await chatHistoryAPI.exportSession(sessionId, format);
      toast.success(`导出会话成功 (${format})`);
    } catch (error) {
      console.error('导出会话失败:', error);
      toast.error('导出会话失败');
    }
  };

  // 选择会话
  const selectSession = (session: ChatSession) => {
    setSelectedSession(session);
    loadMessages(session.id);
  };

  // 初始加载
  useEffect(() => {
    loadSessions();
    loadStats();
    loadWordFrequencies();
  }, []);

  return (
    <div className="bg-gradient-to-br from-blue-50 via-white to-purple-50 min-h-screen flex flex-col">
      <Navbar />
      <div className="flex flex-1">
        <Sidebar />
        <main className="flex-1 ml-64 p-4">
          <div className="max-w-7xl mx-auto h-[calc(100vh-6rem)]">
            <motion.header 
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="mb-4"
            >
              <div className="bg-white rounded-xl shadow-md p-4 backdrop-blur-lg bg-opacity-90">
                <div className="flex justify-between items-center">
                  <div className="flex items-center space-x-3">
                    <div className="p-2 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg shadow-md">
                      <i className="fas fa-history text-white text-xl"></i>
                    </div>
                    <div>
                      <h1 className="text-2xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">聊天历史</h1>
                      <p className="text-gray-600 text-sm">查看和管理您的聊天记录</p>
                    </div>
                  </div>
                  <div className="flex space-x-2">
                    <motion.button
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                      onClick={() => setShowStats(!showStats)}
                      className="px-3 py-1.5 bg-white border border-gray-300 rounded-lg font-medium text-gray-700 hover:bg-gray-50 transition-all flex items-center shadow-sm text-sm"
                    >
                      <i className="fas fa-chart-bar mr-1.5"></i>
                      {showStats ? '隐藏统计' : '显示统计'}
                    </motion.button>
                    <motion.button
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                      onClick={() => setShowWordCloud(!showWordCloud)}
                      className="px-3 py-1.5 bg-white border border-gray-300 rounded-lg font-medium text-gray-700 hover:bg-gray-50 transition-all flex items-center shadow-sm text-sm"
                    >
                      <i className="fas fa-cloud mr-1.5"></i>
                      {showWordCloud ? '隐藏词云' : '显示词云'}
                    </motion.button>
                    <motion.button
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                      onClick={() => navigate('/ai-assistant')}
                      className="px-3 py-1.5 bg-white border border-gray-300 rounded-lg font-medium text-gray-700 hover:bg-gray-50 transition-all flex items-center shadow-sm text-sm"
                    >
                      <i className="fas fa-comments mr-1.5"></i>
                      返回聊天
                    </motion.button>
                  </div>
                </div>
              </div>
            </motion.header>

            {/* 统计数据 */}
            {showStats && stats && (
              <motion.div 
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
                className="bg-white rounded-xl shadow-md p-4 mb-4"
              >
                <h2 className="text-lg font-semibold mb-3">聊天统计</h2>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-3">
                  <div className="bg-blue-50 p-3 rounded-lg">
                    <div className="text-xl font-bold text-blue-600">{stats.totalSessions}</div>
                    <div className="text-xs text-gray-600">总会话数</div>
                  </div>
                  <div className="bg-green-50 p-3 rounded-lg">
                    <div className="text-xl font-bold text-green-600">{stats.totalMessages}</div>
                    <div className="text-xs text-gray-600">总消息数</div>
                  </div>
                  <div className="bg-purple-50 p-3 rounded-lg">
                    <div className="text-xl font-bold text-purple-600">{stats.totalTokens}</div>
                    <div className="text-xs text-gray-600">总Token数</div>
                  </div>
                  <div className="bg-yellow-50 p-3 rounded-lg">
                    <div className="text-xl font-bold text-yellow-600">{stats.avgResponseTime}s</div>
                    <div className="text-xs text-gray-600">平均响应时间</div>
                  </div>
                  <div className="bg-indigo-50 p-3 rounded-lg">
                    <div className="text-xl font-bold text-indigo-600">{stats.kbUsageRate}%</div>
                    <div className="text-xs text-gray-600">知识库使用率</div>
                  </div>
                </div>
              </motion.div>
            )}

            {/* 词云 */}
            {showWordCloud && (
              <motion.div 
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
                className="bg-white rounded-xl shadow-md p-4 mb-4"
              >
                <h2 className="text-lg font-semibold mb-3">搜索热词</h2>
                <div className="flex flex-wrap gap-2 justify-center items-center min-h-[120px]">
                  {wordFrequencies.length === 0 ? (
                    <div className="text-gray-500 text-sm">
                      <i className="fas fa-cloud text-2xl mb-2"></i>
                      <p>暂无词频数据</p>
                    </div>
                  ) : (
                    wordFrequencies.map((item, index) => {
                      const fontSize = Math.max(12, Math.min(32, 12 + (item.count / Math.max(...wordFrequencies.map(w => w.count))) * 20));
                      const colors = ['text-blue-500', 'text-purple-500', 'text-green-500', 'text-yellow-500', 'text-red-500', 'text-indigo-500'];
                      const color = colors[index % colors.length];
                      return (
                        <motion.span
                          key={item.word}
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          transition={{ delay: index * 0.05 }}
                          whileHover={{ scale: 1.2 }}
                          className={`${color} font-medium cursor-pointer hover:opacity-80 transition-all`}
                          style={{ fontSize: `${fontSize}px` }}
                          title={`${item.word}: ${item.count}次`}
                        >
                          {item.word}
                        </motion.span>
                      );
                    })
                  )}
                </div>
              </motion.div>
            )}

            <div className="flex gap-3 h-[calc(100%-10rem)]">
              {/* 会话列表 */}
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.5, delay: 0.2 }}
                className="w-80 bg-white rounded-xl shadow-md overflow-hidden flex flex-col"
              >
                <div className="p-3 border-b border-gray-200 bg-gradient-to-r from-blue-50 to-indigo-50">
                  <h2 className="text-base font-semibold text-gray-800">会话列表</h2>
                </div>
                <div className="flex-1 overflow-y-auto p-2">
                  {loading ? (
                    <div className="flex justify-center py-4">
                      <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500"></div>
                    </div>
                  ) : sessions.length === 0 ? (
                    <div className="text-center py-6 text-gray-500">
                      <i className="fas fa-inbox text-2xl mb-2"></i>
                      <p className="text-sm">暂无会话</p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {sessions.map((session) => (
                        <motion.div
                          key={session.id}
                          whileHover={{ scale: 1.02 }}
                          whileTap={{ scale: 0.98 }}
                          className={`p-3 rounded-lg border cursor-pointer transition-all ${
                            selectedSession?.id === session.id
                              ? 'border-blue-500 bg-blue-50'
                              : 'border-gray-200 hover:border-blue-300 hover:bg-blue-50'
                          }`}
                          onClick={() => selectSession(session)}
                        >
                          <div className="flex justify-between items-start">
                            <div className="flex-1 min-w-0">
                              <h3 className="font-medium text-gray-800 text-sm truncate">{session.title}</h3>
                              <p className="text-xs text-gray-500 mt-1">
                                {formatTimeAgo(session.updatedAt)}
                              </p>
                              <p className="text-xs text-gray-400 mt-1">{session.messageCount} 条消息</p>
                            </div>
                            <div className="flex space-x-1">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  exportSession(session.id, 'json');
                                }}
                                className="p-1.5 text-blue-500 hover:bg-blue-100 rounded-lg transition-colors"
                                title="导出为JSON"
                              >
                                <i className="fas fa-download text-xs"></i>
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  deleteSession(session.id);
                                }}
                                className="p-1.5 text-red-500 hover:bg-red-100 rounded-lg transition-colors"
                                title="删除会话"
                              >
                                <i className="fas fa-trash-alt text-xs"></i>
                              </button>
                            </div>
                          </div>
                        </motion.div>
                      ))}
                    </div>
                  )}
                </div>
              </motion.div>

              {/* 消息列表 */}
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.3 }}
                className="flex-1 bg-white rounded-xl shadow-md overflow-hidden flex flex-col"
              >
                <div className="p-3 border-b border-gray-200 bg-gradient-to-r from-blue-50 to-indigo-50">
                  <h2 className="text-base font-semibold text-gray-800">
                    {selectedSession ? `消息 - ${selectedSession.title}` : '选择一个会话查看消息'}
                  </h2>
                </div>
                <div className="flex-1 overflow-y-auto p-3">
                  {selectedSession ? (
                    loadingMessages ? (
                      <div className="flex justify-center py-4">
                        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500"></div>
                      </div>
                    ) : messages.length === 0 ? (
                      <div className="text-center text-gray-500 py-6">
                        <i className="fas fa-comments text-2xl mb-2"></i>
                        <p>暂无消息</p>
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {messages.map((message) => (
                          <div
                            key={message.id}
                            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                          >
                            <div
                              className={`max-w-[80%] px-3 py-2 rounded-lg ${
                                message.role === 'user'
                                  ? 'bg-blue-500 text-white'
                                  : 'bg-gray-200 text-gray-800'
                              }`}
                            >
                              <p className="text-sm">{message.content}</p>
                              <p className={`text-xs mt-1 ${
                                message.role === 'user' ? 'text-blue-100' : 'text-gray-500'
                              }`}>
                                {formatTimeAgo(message.timestamp)}
                              </p>
                            </div>
                          </div>
                        ))}
                      </div>
                    )
                  ) : (
                    <div className="text-center text-gray-500 py-6">
                      <i className="fas fa-mouse-pointer text-2xl mb-2"></i>
                      <p>请从左侧选择一个会话</p>
                    </div>
                  )}
                </div>
              </motion.div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
};

export default ChatHistory;