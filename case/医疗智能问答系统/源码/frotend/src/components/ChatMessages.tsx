import React, { useState, useEffect } from 'react';
import { chatHistoryAPI } from '../services/api';
import { formatDistanceToNow } from 'date-fns';
import { zhCN } from 'date-fns/locale';
import { Button, Input, Radio, Dialog, MessagePlugin, Tag, Space } from 'tdesign-react';
import { EditIcon, DownloadIcon, DeleteIcon, TimeIcon } from 'tdesign-icons-react';

interface ChatMessage {
  id: string;
  content: string;
  message_type: 'user' | 'ai';
  created_at: string;
  source?: string;
}

interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

interface ChatMessagesProps {
  sessionId: string;
  onSessionUpdate?: (session: ChatSession) => void;
  refreshTrigger?: number;
}

const ChatMessages: React.FC<ChatMessagesProps> = ({
  sessionId,
  onSessionUpdate,
  refreshTrigger
}) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [showEditTitleDialog, setShowEditTitleDialog] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [showExportDialog, setShowExportDialog] = useState(false);
  const [exportFormat, setExportFormat] = useState<'json' | 'txt' | 'csv'>('json');
  const [exporting, setExporting] = useState(false);

  // 加载会话信息
  const loadSession = async () => {
    try {
      const response = await chatHistoryAPI.getSession(sessionId);
      
      if (response.success) {
        setSession(response.data);
        setNewTitle(response.data.title);
        onSessionUpdate?.(response.data);
      } else {
        setError(response.message || '获取会话信息失败');
      }
    } catch (err) {
      setError('获取会话信息时发生错误');
      console.error('Failed to load session:', err);
    }
  };

  // 加载消息列表
  const loadMessages = async (pageNum = 1) => {
    try {
      setLoading(true);
      const response = await chatHistoryAPI.getMessages(sessionId, {
        page: pageNum,
        per_page: 50
      });
      
      if (response.success) {
        if (pageNum === 1) {
          setMessages(response.data.items.reverse()); // 反转以显示正确的顺序
        } else {
          setMessages(prev => [...response.data.items.reverse(), ...prev]); // 新消息在前面
        }
        setTotalPages(response.data.total_pages);
      } else {
        setError(response.message || '获取消息列表失败');
      }
    } catch (err) {
      setError('获取消息列表时发生错误');
      console.error('Failed to load messages:', err);
    } finally {
      setLoading(false);
    }
  };

  // 更新会话标题
  const updateSessionTitle = async () => {
    try {
      const response = await chatHistoryAPI.updateSession(sessionId, {
        title: newTitle
      });
      
      if (response.success) {
        setShowEditTitleDialog(false);
        loadSession(); // 重新加载会话信息
      } else {
        setError(response.message || '更新会话标题失败');
      }
    } catch (err) {
      setError('更新会话标题时发生错误');
      console.error('Failed to update session title:', err);
    }
  };

  // 删除消息
  const deleteMessage = async (messageId: string) => {
    if (!window.confirm('确定要删除这条消息吗？此操作不可撤销。')) {
      return;
    }
    
    try {
      const response = await chatHistoryAPI.deleteMessage(sessionId, messageId);
      
      if (response.success) {
        // 从列表中移除该消息
        setMessages(prev => prev.filter(msg => msg.id !== messageId));
      } else {
        setError(response.message || '删除消息失败');
      }
    } catch (err) {
      setError('删除消息时发生错误');
      console.error('Failed to delete message:', err);
    }
  };

  // 导出会话
  const exportSession = async () => {
    try {
      setExporting(true);
      await chatHistoryAPI.exportSession(sessionId, exportFormat);
      setShowExportDialog(false);
    } catch (err) {
      setError('导出会话时发生错误');
      console.error('Failed to export session:', err);
    } finally {
      setExporting(false);
    }
  };

  // 加载更多消息
  const loadMore = () => {
    if (page < totalPages) {
      const nextPage = page + 1;
      setPage(nextPage);
      loadMessages(nextPage);
    }
  };

  // 初始加载和刷新
  useEffect(() => {
    if (sessionId) {
      loadSession();
      setPage(1);
      loadMessages(1);
    }
  }, [sessionId, refreshTrigger]);

  if (!sessionId) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', background: '#f5f5f5' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ color: '#666', fontSize: 16, marginBottom: 8 }}>请选择一个会话</div>
          <div style={{ color: '#999', fontSize: 14 }}>从左侧列表中选择一个会话以查看聊天记录</div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#f5f5f5' }}>
      {/* 头部 */}
      <div style={{ background: '#fff', borderBottom: '1px solid #e5e5e5', padding: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2 style={{ fontSize: 18, fontWeight: 500, color: '#333', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{session?.title}</h2>
            <div style={{ marginTop: 4, fontSize: 12, color: '#999' }}>
              <span>
                创建于 {session && formatDistanceToNow(new Date(session.created_at), {
                  addSuffix: true,
                  locale: zhCN
                })}
              </span>
              <span style={{ margin: '0 4px' }}>·</span>
              <span>
                更新于 {session && formatDistanceToNow(new Date(session.updated_at), {
                  addSuffix: true,
                  locale: zhCN
                })}
              </span>
            </div>
          </div>
          <Space>
            <Button
              theme="default"
              variant="text"
              icon={<EditIcon />}
              onClick={() => setShowEditTitleDialog(true)}
              title="编辑标题"
            />
            <Button
              theme="default"
              variant="text"
              icon={<DownloadIcon />}
              onClick={() => setShowExportDialog(true)}
              title="导出会话"
            />
          </Space>
        </div>
      </div>

      {/* 消息列表 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        {loading && messages.length === 0 ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 128 }}>
            <div style={{ fontSize: 14, color: '#666' }}>加载中...</div>
          </div>
        ) : error ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 128 }}>
            <div style={{ fontSize: 14, color: '#f56c6c' }}>{error}</div>
          </div>
        ) : messages.length === 0 ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 128 }}>
            <div style={{ fontSize: 14, color: '#666' }}>暂无消息</div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {page < totalPages && (
              <div style={{ textAlign: 'center' }}>
                <Button
                  theme="default"
                  variant="text"
                  onClick={loadMore}
                >
                  加载更早的消息
                </Button>
              </div>
            )}
            {messages.map((message) => (
              <div
                key={message.id}
                style={{ display: 'flex', justifyContent: message.message_type === 'user' ? 'flex-end' : 'flex-start' }}
              >
                <div
                  style={{
                    maxWidth: '75%',
                    padding: '12px 16px',
                    borderRadius: 8,
                    backgroundColor: message.message_type === 'user' ? '#3b82f6' : '#fff',
                    color: message.message_type === 'user' ? '#fff' : '#333',
                    border: message.message_type === 'user' ? 'none' : '1px solid #e5e5e5'
                  }}
                >
                  <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{message.content}</div>
                  <div style={{ marginTop: 4, fontSize: 12, color: message.message_type === 'user' ? 'rgba(255,255,255,0.7)' : '#999' }}>
                    {formatDistanceToNow(new Date(message.created_at), {
                      addSuffix: true,
                      locale: zhCN
                    })}
                    {message.source && (
                      <span style={{ marginLeft: 4 }}>· {message.source}</span>
                    )}
                    <Button
                      theme="danger"
                      variant="text"
                      size="small"
                      icon={<DeleteIcon />}
                      onClick={() => deleteMessage(message.id)}
                      style={{ marginLeft: 8, padding: 0, minWidth: 'auto' }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 编辑标题对话框 */}
      <Dialog
        header="编辑会话标题"
        visible={showEditTitleDialog}
        onClose={() => {
          setShowEditTitleDialog(false);
          setNewTitle(session?.title || '');
        }}
        onConfirm={updateSessionTitle}
        cancelBtn="取消"
        confirmBtn="保存"
      >
        <div style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 8, fontSize: 14, fontWeight: 500 }}>会话标题</div>
          <Input
            value={newTitle}
            onChange={(val) => setNewTitle(val as string)}
            placeholder="请输入会话标题"
          />
        </div>
      </Dialog>

      {/* 导出对话框 */}
      <Dialog
        header="导出会话"
        visible={showExportDialog}
        onClose={() => setShowExportDialog(false)}
        onConfirm={exportSession}
        confirmBtnLoading={exporting}
        cancelBtn="取消"
        confirmBtn={exporting ? '导出中...' : '导出'}
      >
        <div style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 8, fontSize: 14, fontWeight: 500 }}>导出格式</div>
          <Radio.Group
            value={exportFormat}
            onChange={(val) => setExportFormat(val as 'json' | 'txt' | 'csv')}
            options={[
              { label: 'JSON (完整数据)', value: 'json' },
              { label: 'TXT (纯文本)', value: 'txt' },
              { label: 'CSV (表格格式)', value: 'csv' }
            ]}
          />
        </div>
      </Dialog>
    </div>
  );
};

export default ChatMessages;