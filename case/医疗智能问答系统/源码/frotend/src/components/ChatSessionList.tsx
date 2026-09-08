import React, { useState, useEffect } from 'react';
import { chatHistoryAPI } from '../services/api';
import { formatDistanceToNow } from 'date-fns';
import { zhCN } from 'date-fns/locale';
import { Button, Input, Dialog, MessagePlugin, Space } from 'tdesign-react';
import { AddIcon, SearchIcon, DeleteIcon } from 'tdesign-icons-react';

interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

interface ChatSessionListProps {
  onSelectSession: (sessionId: string) => void;
  currentSessionId?: string;
  refreshTrigger?: number;
}

const ChatSessionList: React.FC<ChatSessionListProps> = ({
  onSelectSession,
  currentSessionId,
  refreshTrigger
}) => {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [showNewSessionDialog, setShowNewSessionDialog] = useState(false);
  const [newSessionTitle, setNewSessionTitle] = useState('');

  // 加载会话列表
  const loadSessions = async (pageNum = 1, query = '') => {
    try {
      setLoading(true);
      const response = await chatHistoryAPI.getSessions({
        page: pageNum,
        per_page: 20,
        search: query || undefined
      });
      
      if (response.success) {
        if (pageNum === 1) {
          setSessions(response.data.items);
        } else {
          setSessions(prev => [...prev, ...response.data.items]);
        }
        setTotalPages(response.data.total_pages);
      } else {
        setError(response.message || '获取会话列表失败');
      }
    } catch (err) {
      setError('获取会话列表时发生错误');
      console.error('Failed to load sessions:', err);
    } finally {
      setLoading(false);
    }
  };

  // 创建新会话
  const createNewSession = async () => {
    try {
      const response = await chatHistoryAPI.createSession({
        title: newSessionTitle || `新会话 ${new Date().toLocaleString()}`
      });
      
      if (response.success) {
        setShowNewSessionDialog(false);
        setNewSessionTitle('');
        // 刷新会话列表并选择新创建的会话
        loadSessions(1, searchQuery);
        onSelectSession(response.data.id);
      } else {
        setError(response.message || '创建会话失败');
      }
    } catch (err) {
      setError('创建会话时发生错误');
      console.error('Failed to create session:', err);
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
        // 如果删除的是当前会话，则清空选择
        if (sessionId === currentSessionId) {
          onSelectSession('');
        }
        // 刷新会话列表
        loadSessions(1, searchQuery);
      } else {
        setError(response.message || '删除会话失败');
      }
    } catch (err) {
      setError('删除会话时发生错误');
      console.error('Failed to delete session:', err);
    }
  };

  // 搜索处理
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    loadSessions(1, searchQuery);
  };

  // 加载更多
  const loadMore = () => {
    if (page < totalPages) {
      const nextPage = page + 1;
      setPage(nextPage);
      loadSessions(nextPage, searchQuery);
    }
  };

  // 初始加载和刷新
  useEffect(() => {
    loadSessions(1, searchQuery);
  }, [refreshTrigger]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#fff', borderRight: '1px solid #e5e5e5' }}>
      {/* 头部 */}
      <div style={{ padding: 16, borderBottom: '1px solid #e5e5e5' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <h2 style={{ fontSize: 18, fontWeight: 500, color: '#333', margin: 0 }}>聊天记录</h2>
          <Button
            theme="primary"
            icon={<AddIcon />}
            onClick={() => setShowNewSessionDialog(true)}
          >
            新建会话
          </Button>
        </div>
        
        {/* 搜索框 */}
        <form onSubmit={handleSearch} style={{ display: 'flex' }}>
          <Input
            value={searchQuery}
            onChange={(val) => setSearchQuery(val as string)}
            placeholder="搜索会话..."
            style={{ flex: 1 }}
          />
          <Button
            theme="default"
            icon={<SearchIcon />}
            onClick={handleSearch}
            style={{ marginLeft: 8 }}
          />
        </form>
      </div>

      {/* 会话列表 */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {loading && sessions.length === 0 ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 128 }}>
            <div style={{ fontSize: 14, color: '#666' }}>加载中...</div>
          </div>
        ) : error ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 128 }}>
            <div style={{ fontSize: 14, color: '#f56c6c' }}>{error}</div>
          </div>
        ) : sessions.length === 0 ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 128 }}>
            <div style={{ fontSize: 14, color: '#666' }}>暂无会话记录</div>
          </div>
        ) : (
          <div>
            {sessions.map((session) => (
              <div
                key={session.id}
                style={{
                  padding: 16,
                  borderBottom: '1px solid #f0f0f0',
                  cursor: 'pointer',
                  backgroundColor: currentSessionId === session.id ? '#e6f7ff' : 'transparent'
                }}
                onClick={() => onSelectSession(session.id)}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <h3 style={{ fontSize: 14, fontWeight: 500, color: '#333', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {session.title}
                    </h3>
                    <div style={{ marginTop: 4, fontSize: 12, color: '#999' }}>
                      <span>{session.message_count} 条消息</span>
                      <span style={{ margin: '0 4px' }}>·</span>
                      <span>
                        {formatDistanceToNow(new Date(session.updated_at), {
                          addSuffix: true,
                          locale: zhCN
                        })}
                      </span>
                    </div>
                  </div>
                  <Button
                    theme="danger"
                    variant="text"
                    icon={<DeleteIcon />}
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteSession(session.id);
                    }}
                    style={{ padding: 0, minWidth: 'auto' }}
                  />
                </div>
              </div>
            ))}
            {page < totalPages && (
              <div style={{ padding: 16, textAlign: 'center' }}>
                <Button
                  theme="default"
                  variant="text"
                  onClick={loadMore}
                >
                  加载更多
                </Button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 新建会话对话框 */}
      <Dialog
        header="创建新会话"
        visible={showNewSessionDialog}
        onClose={() => {
          setShowNewSessionDialog(false);
          setNewSessionTitle('');
        }}
        onConfirm={createNewSession}
        cancelBtn="取消"
        confirmBtn="创建"
      >
        <div style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 8, fontSize: 14, fontWeight: 500 }}>会话标题</div>
          <Input
            value={newSessionTitle}
            onChange={(val) => setNewSessionTitle(val as string)}
            placeholder="可选，留空将使用默认标题"
          />
        </div>
      </Dialog>
    </div>
  );
};

export default ChatSessionList;