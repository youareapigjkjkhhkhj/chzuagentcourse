import { useContext, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AuthContext } from '../contexts/authContext';
import { SystemStats, DiagnosisLevel as DiagnosisLevelType } from '../types';
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import Navbar from '../components/Navbar';
import Sidebar from '../components/Sidebar';
import DiagnosisLevel from '../components/DiagnosisLevel';
import { Card, Row, Col, Statistic, Table, Button, Loading, MessagePlugin } from 'tdesign-react';
import { getDiagnosisColor, getDiagnosisName } from '../types';
import { imageAnalysisAPI } from '../services/api';

// 初始化空统计数据
const emptyStats: SystemStats = {
  totalReports: 0,
  highRiskCases: 0,
  activeUsers: 0,
  dailyReports: 0,
  diagnosisDistribution: []
};

// 将诊断级别转换为十六进制颜色值
const getHexColor = (level: DiagnosisLevelType): string => {
  const colors: Record<DiagnosisLevelType, string> = {
    'NoDR': '#10b981',      // green-500
    'Mild': '#eab308',       // yellow-500
    'Moderate': '#f97316',   // orange-500
    'Severe': '#ef4444',     // red-500
    'Proliferative': '#b91c1c' // red-700
  };
  return colors[level];
};

// 将中文诊断级别名称映射到英文诊断级别
const mapChineseToEnglishLevel = (chineseLevel: string): DiagnosisLevelType => {
  const mapping: Record<string, DiagnosisLevelType> = {
    '无明显视网膜病变': 'NoDR',
    '轻度非增殖性糖尿病视网膜病变': 'Mild',
    '中度非增殖性糖尿病视网膜病变': 'Moderate',
    '重度非增殖性糖尿病视网膜病变': 'Severe',
    '增殖性糖尿病视网膜病变': 'Proliferative'
  };
  return mapping[chineseLevel] || 'NoDR'; // 默认返回NoDR如果找不到匹配
};

export default function Dashboard() {
  const { user } = useContext(AuthContext);
  const navigate = useNavigate();
  const [stats, setStats] = useState<SystemStats>(emptyStats);
  const [recentReports, setRecentReports] = useState([]);
  const [loading, setLoading] = useState(true);

  // 加载统计数据和最近报告
  useEffect(() => {
    const loadDashboardData = async () => {
      try {
        setLoading(true);
        
        // 并行加载统计数据和最近报告
        const [statsResponse, reportsResponse] = await Promise.all([
          imageAnalysisAPI.getAnalysisStatsForDashboard().catch(() => ({ data: { stats: emptyStats } })),
          imageAnalysisAPI.getAnalysisHistory().catch(() => ({ data: { histories: [] } }))
        ]);
        
        setStats(statsResponse.data?.stats || emptyStats);
        setRecentReports((reportsResponse.data?.histories || []).slice(0, 5));
        
      } catch (error) {
        console.error('加载仪表盘数据失败:', error);
        toast.error('加载数据失败，请刷新重试');
        setStats(emptyStats);
        setRecentReports([]);
      } finally {
        setLoading(false);
      }
    };

    loadDashboardData();
  }, []);

  // 格式化大数字
  const formatNumber = (num: number): string => {
    if (num >= 10000) {
      return `${(num / 10000).toFixed(1)}万`;
    }
    return num.toString();
  };

  // 跳转到报告详情页
  const handleViewDetails = (reportId: string) => {
    navigate(`/reports/${reportId}`);
  };

  // 饼图数据
  const pieData = stats.diagnosisDistribution.map(item => ({
    name: getDiagnosisName(item.level),
    value: item.count,
    color: getHexColor(item.level)
  }));

  // 柱状图数据
  const barData = stats.diagnosisDistribution.map(item => ({
    name: getDiagnosisName(item.level).replace('明显', '').replace('非', ''),
    病例数: item.count,
    百分比: item.percentage
  }));

  const columns = [
    { colKey: 'patient_id', title: '患者ID', width: '120px' },
    { colKey: 'patient_name', title: '患者姓名', width: '120px', render: (row: any) => row.patient_name || '-' },
    { 
      colKey: 'diagnosis_level_name', 
      title: '诊断结果', 
      width: '200px',
      render: (row: any) => <DiagnosisLevel level={mapChineseToEnglishLevel(row.diagnosis_level_name)} size="small" />
    },
    { 
      colKey: 'created_at', 
      title: '创建时间', 
      width: '180px',
      render: (row: any) => new Date(row.created_at).toLocaleString('zh-CN')
    },
    {
      colKey: 'action',
      title: '操作',
      width: '100px',
      render: (row: any) => (
        <Button theme="primary" variant="text" onClick={() => handleViewDetails(row.report_id)}>
          查看详情
        </Button>
      )
    }
  ];

  return (
    <div style={{ minHeight: '100vh', background: '#f5f5f5' }}>
      <Navbar />
      <div style={{ display: 'flex' }}>
        <Sidebar />
        <main style={{ flex: 1, marginLeft: 256, padding: 24 }}>
          <div style={{ maxWidth: 1200, margin: '0 auto' }}>
            <header style={{ marginBottom: 32 }}>
              <h1 style={{ fontSize: 24, fontWeight: 'bold', color: '#333', margin: 0 }}>仪表盘</h1>
              <p style={{ color: '#666', marginTop: 4 }}>欢迎回来，{user?.name}！这是您的系统概览。</p>
            </header>
            
            {loading ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 256 }}>
                <Loading size="large" />
                <span style={{ marginLeft: 16, color: '#666' }}>正在加载数据...</span>
              </div>
            ) : (
              <>
                <Row gutter={[24, 24]} style={{ marginBottom: 32 }}>
                  <Col span={6}>
                    <Card>
                      <Statistic title="总报告数" value={stats.totalReports} />
                    </Card>
                  </Col>
                  <Col span={6}>
                    <Card>
                      <Statistic title="高风险病例" value={stats.highRiskCases} theme="danger" />
                    </Card>
                  </Col>
                  <Col span={6}>
                    <Card>
                      <Statistic title="活跃用户" value={stats.activeUsers} theme="success" />
                    </Card>
                  </Col>
                  <Col span={6}>
                    <Card>
                      <Statistic title="今日报告" value={stats.dailyReports} theme="primary" />
                    </Card>
                  </Col>
                </Row>
                
                <Row gutter={[24, 24]} style={{ marginBottom: 32 }}>
                  <Col span={12}>
                    <Card title="诊断结果分布">
                      {pieData.length > 0 ? (
                        <div style={{ height: 320 }}>
                          <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                              <Pie
                                data={pieData}
                                cx="50%"
                                cy="50%"
                                labelLine={false}
                                outerRadius={100}
                                fill="#8884d8"
                                dataKey="value"
                                label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                              >
                                {pieData.map((entry, index) => (
                                  <Cell key={`cell-${index}`} fill={entry.color} />
                                ))}
                              </Pie>
                              <Tooltip formatter={(value) => [`${value} 例`, '数量']} />
                              <Legend />
                            </PieChart>
                          </ResponsiveContainer>
                        </div>
                      ) : (
                        <div style={{ height: 320, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
                          暂无数据
                        </div>
                      )}
                    </Card>
                  </Col>
                  <Col span={12}>
                    <Card title="诊断级别统计">
                      {barData.length > 0 ? (
                        <div style={{ height: 320 }}>
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart
                              data={barData}
                              margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
                            >
                              <CartesianGrid strokeDasharray="3 3" />
                              <XAxis dataKey="name" />
                              <YAxis yAxisId="left" orientation="left" />
                              <YAxis yAxisId="right" orientation="right" />
                              <Tooltip />
                              <Legend />
                              <Bar yAxisId="left" dataKey="病例数" fill="#3b82f6" />
                              <Bar yAxisId="right" dataKey="百分比" fill="#10b981" />
                            </BarChart>
                          </ResponsiveContainer>
                        </div>
                      ) : (
                        <div style={{ height: 320, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
                          暂无数据
                        </div>
                      )}
                    </Card>
                  </Col>
                </Row>
                
                <Card title="最近报告">
                  {recentReports.length > 0 ? (
                    <Table
                      data={recentReports}
                      columns={columns}
                      rowKey="id"
                      hover
                    />
                  ) : (
                    <div style={{ textAlign: 'center', padding: 32, color: '#999' }}>
                      暂无报告数据
                    </div>
                  )}
                </Card>
              </>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}