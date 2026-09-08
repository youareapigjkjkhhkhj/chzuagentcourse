import React, { useState } from 'react';
import ChatSessionList from '../components/ChatSessionList';
import ChatMessages from '../components/ChatMessages';
import ChatStats from '../components/ChatStats';

interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

const ChatHistoryPage: React.FC = () => {
  const [selectedSessionId, setSelectedSessionId] = useState<string>('');
  const [selectedSession, setSelectedSession] = useState<ChatSession | null>(null);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  // 处理会话选择
  const handleSelectSession = (sessionId: string) => {
    setSelectedSessionId(sessionId);
  };

  // 处理会话更新
  const handleSessionUpdate = (session: ChatSession) => {
    setSelectedSession(session);
  };

  // 刷新列表
  const refreshList = () => {
    setRefreshTrigger(prev => prev + 1);
  };

  return (
    <div className="flex flex-col h-screen bg-gray-100">
      {/* 头部 */}
      <div className="bg-white shadow-sm border-b border-gray-200 p-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <h1 className="text-2xl font-bold text-gray-900">聊天记录</h1>
          <button
            onClick={refreshList}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            刷新
          </button>
        </div>
      </div>

      {/* 主体内容 */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧会话列表 */}
        <div className="w-80 flex-shrink-0">
          <ChatSessionList
            onSelectSession={handleSelectSession}
            currentSessionId={selectedSessionId}
            refreshTrigger={refreshTrigger}
          />
        </div>

        {/* 右侧内容区域 */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {selectedSessionId ? (
            <ChatMessages
              sessionId={selectedSessionId}
              onSessionUpdate={handleSessionUpdate}
              refreshTrigger={refreshTrigger}
            />
          ) : (
            <div className="flex-1 flex flex-col overflow-y-auto p-6">
              <div className="max-w-4xl mx-auto w-full space-y-6">
                <div className="bg-white rounded-lg shadow p-6">
                  <h2 className="text-lg font-medium text-gray-900 mb-4">欢迎使用聊天记录功能</h2>
                  <div className="text-gray-600 space-y-2">
                    <p>在这里您可以查看和管理所有的聊天记录：</p>
                    <ul className="list-disc pl-5 space-y-1">
                      <li>查看所有聊天会话列表</li>
                      <li>浏览会话中的详细消息</li>
                      <li>编辑会话标题</li>
                      <li>删除不需要的会话或消息</li>
                      <li>导出会话记录</li>
                    </ul>
                  </div>
                </div>
                
                <ChatStats refreshTrigger={refreshTrigger} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ChatHistoryPage;