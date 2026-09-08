import React, { useState, useEffect } from 'react';
import { chatHistoryAPI } from '../services/api';
import { Card, Statistic, Row, Col, Skeleton } from 'tdesign-react';

interface ChatStats {
  total_sessions: number;
  total_messages: number;
  user_messages: number;
  ai_messages: number;
  average_messages_per_session: number;
  most_active_day: string;
}

interface ChatStatsProps {
  refreshTrigger?: number;
}

const ChatStats: React.FC<ChatStatsProps> = ({ refreshTrigger }) => {
  const [stats, setStats] = useState<ChatStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 加载统计数据
  const loadStats = async () => {
    try {
      setLoading(true);
      const response = await chatHistoryAPI.getChatStats();
      
      if (response.success) {
        setStats(response.data);
      } else {
        setError(response.message || '获取统计数据失败');
      }
    } catch (err) {
      setError('获取统计数据时发生错误');
      console.error('Failed to load stats:', err);
    } finally {
      setLoading(false);
    }
  };

  // 初始加载和刷新
  useEffect(() => {
    loadStats();
  }, [refreshTrigger]);

  return (
    <Card title="聊天统计">
      {loading ? (
        <Skeleton paragraph={{ rows: 4 }} />
      ) : error ? (
        <div style={{ textAlign: 'center', color: '#f56c6c', padding: 32 }}>{error}</div>
      ) : stats ? (
        <Row gutter={16}>
          <Col span={12}>
            <Statistic title="总会话数" value={stats.total_sessions} />
          </Col>
          <Col span={12}>
            <Statistic title="总消息数" value={stats.total_messages} />
          </Col>
          <Col span={12}>
            <Statistic title="用户消息" value={stats.user_messages} />
          </Col>
          <Col span={12}>
            <Statistic title="AI回复" value={stats.ai_messages} />
          </Col>
          <Col span={12}>
            <Statistic title="平均每会话消息数" value={stats.average_messages_per_session.toFixed(1)} />
          </Col>
          <Col span={12}>
            <Statistic title="最活跃日期" value={stats.most_active_day || '无数据'} />
          </Col>
        </Row>
      ) : (
        <div style={{ textAlign: 'center', color: '#666', padding: 32 }}>暂无统计数据</div>
      )}
    </Card>
  );
};

export default ChatStats;