import { useContext, useState, useEffect, useRef } from 'react';
import { AuthContext } from '../contexts/authContext';
import { useNavigate } from 'react-router-dom';
import Navbar from '../components/Navbar';
import Sidebar from '../components/Sidebar';
import ReportCard from '../components/ReportCard';
import { motion } from 'framer-motion';
import { DiagnosisReport, DiagnosisLevel as DiagnosisLevelType } from '../types';
import { toast } from 'sonner';
import { imageAnalysisAPI, reportsAPI, buildFileUrl } from '../services/api';

export default function ReportList() {
  const { user } = useContext(AuthContext);
  const navigate = useNavigate();
  const [reports, setReports] = useState<DiagnosisReport[]>([]);
  const [filteredReports, setFilteredReports] = useState<DiagnosisReport[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedLevel, setSelectedLevel] = useState<DiagnosisLevelType | 'all'>('all');
  const [sortBy, setSortBy] = useState<'created_at' | 'patient_id'>('created_at');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [isLoading, setIsLoading] = useState(false);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const exportMenuRef = useRef<HTMLDivElement>(null);

  // 加载报告数据
  useEffect(() => {
    loadReports();
  }, []);

  // 点击外部关闭导出菜单
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(event.target as Node)) {
        setShowExportMenu(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  // 应用筛选和排序
  useEffect(() => {
    applyFilters();
  }, [reports, searchTerm, selectedLevel, sortBy, sortOrder]);

  const loadReports = async () => {
    try {
      setIsLoading(true);
      const response = await reportsAPI.getReports();
      const reportData = response.data?.reports || [];

      const levelMap: Record<number, DiagnosisLevelType> = {
        0: 'NoDR',
        1: 'Mild',
        2: 'Moderate',
        3: 'Severe',
        4: 'Proliferative'
      };

      const transformedReports: DiagnosisReport[] = reportData.map((report: any) => {
        const analysisResultsFromDb = (report.analysis_results || []) as any[];
        const modelPredictionsFromContent = (report.report_content?.model_predictions || []) as any[];

        let analysisResults = analysisResultsFromDb.map((ar: any) => ({
          model: ar.model_name as any,
          level: levelMap[ar.prediction_level as number] ?? 'NoDR',
          confidence: ar.confidence_score || 0,
          features: ar.model_prediction?.features || [],
          analysisTime: ar.created_at || report.created_at
        }));

        if (analysisResults.length === 0 && Array.isArray(modelPredictionsFromContent)) {
          analysisResults = modelPredictionsFromContent.map((mp: any) => ({
            model: mp.model as any,
            level: (mp.level as DiagnosisLevelType) || 'NoDR',
            confidence: mp.confidence || 0,
            features: mp.features || [],
            analysisTime: report.created_at
          }));
        }

        return {
          id: report.id,
          patientId: report.patient_id,
          patientName: report.patient_name || '',
          imageUrl: buildFileUrl(report.original_image_url),
          analysisResults,
          finalDiagnosis: levelMap[report.ensemble_diagnosis_level as number] ?? 'NoDR',
          clinicalSummary: report.report_content?.clinical_summary || '',
          createdBy: 'system',
          createdAt: report.created_at,
          updatedAt: report.created_at
        };
      });
      
      setReports(transformedReports);
    } catch (error) {
      console.error('加载报告失败:', error);
      toast.error('加载报告数据失败，请刷新重试');
      setReports([]);
    } finally {
      setIsLoading(false);
    }
  };

  const applyFilters = () => {
    let result = [...reports];
    
    // 搜索筛选
    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      result = result.filter(report => 
        report.patientId.toLowerCase().includes(term) ||
        (report.patientName && report.patientName.toLowerCase().includes(term))
      );
    }
    
    // 诊断级别筛选
    if (selectedLevel !== 'all') {
      result = result.filter(report => report.finalDiagnosis === selectedLevel);
    }
    
    // 排序
    result.sort((a, b) => {
      let comparison = 0;
      if (sortBy === 'created_at') {
        comparison = new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime();
      } else if (sortBy === 'patient_id') {
        comparison = a.patientId.localeCompare(b.patientId);
      }
      return sortOrder === 'asc' ? comparison : -comparison;
    });
    
    setFilteredReports(result);
  };

  const handleReportClick = (report: DiagnosisReport) => {
    navigate(`/reports/${report.id}`);
  };

  const handleExportReports = async (format: 'excel' | 'pdf' = 'pdf') => {
    try {
      if (filteredReports.length === 0) {
        toast.error('没有可导出的报告数据');
        return;
      }

      toast.info('正在准备导出数据...');
      
      const reportIds = filteredReports.map(report => report.id);
      await reportsAPI.exportReports(reportIds, format === 'excel' ? 'excel' : 'pdf');
      
      toast.success(`报告导出请求已发送（${format.toUpperCase()}格式）`);
    } catch (error) {
      console.error('导出报告失败:', error);
      toast.error('导出报告失败，请重试');
    }
  };

  // 处理单个报告的PDF导出
  const handleSingleReportPDFExport = (report: DiagnosisReport) => {
    try {
      // 创建一个新的窗口用于打印
      const printWindow = window.open('', '_blank');
      if (!printWindow) {
        toast.error('无法打开打印窗口，请检查浏览器弹窗设置');
        return;
      }

      // 获取诊断级别的中文名称
      const getDiagnosisName = (level: DiagnosisLevelType): string => {
        const levelMap: Record<DiagnosisLevelType, string> = {
          'NoDR': '无明显视网膜病变',
          'Mild': '轻度非增殖性',
          'Moderate': '中度非增殖性',
          'Severe': '重度非增殖性',
          'Proliferative': '增殖性'
        };
        return levelMap[level] || '未知';
      };

      // 格式化日期
      const formatDate = (dateString: string): string => {
        const date = new Date(dateString);
        return date.toLocaleDateString('zh-CN', {
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit'
        });
      };

      // 生成HTML内容
      const htmlContent = `
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
          <meta charset="UTF-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>糖尿病视网膜病变诊断报告</title>
          <style>
            body {
              font-family: 'Microsoft YaHei', sans-serif;
              margin: 0;
              padding: 20px;
              color: #333;
            }
            .header {
              text-align: center;
              margin-bottom: 30px;
              border-bottom: 2px solid #eee;
              padding-bottom: 20px;
            }
            .header h1 {
              margin: 0;
              color: #1e40af;
            }
            .header p {
              margin: 5px 0 0;
              color: #666;
            }
            .report {
              margin-bottom: 25px;
              border: 1px solid #ddd;
              border-radius: 8px;
              padding: 15px;
              page-break-inside: avoid;
            }
            .report-header {
              display: flex;
              justify-content: space-between;
              margin-bottom: 10px;
              border-bottom: 1px solid #eee;
              padding-bottom: 8px;
            }
            .patient-info {
              margin-bottom: 10px;
            }
            .diagnosis {
              margin: 10px 0;
            }
            .diagnosis-level {
              display: inline-block;
              padding: 3px 8px;
              border-radius: 4px;
              color: white;
              font-weight: bold;
              margin-right: 10px;
            }
            .NoDR { background-color: #10b981; }
            .Mild { background-color: #eab308; }
            .Moderate { background-color: #f97316; }
            .Severe { background-color: #ef4444; }
            .Proliferative { background-color: #b91c1c; }
            .summary {
              margin-top: 10px;
              background-color: #f9f9f9;
              padding: 10px;
              border-radius: 4px;
            }
            .image-section {
              margin-top: 15px;
              text-align: center;
            }
            .image-section img {
              max-width: 100%;
              height: auto;
              border: 1px solid #ddd;
              border-radius: 4px;
            }
            .footer {
              margin-top: 30px;
              text-align: center;
              font-size: 12px;
              color: #666;
              border-top: 1px solid #eee;
              padding-top: 15px;
            }
            @media print {
              body { margin: 0; }
              .no-print { display: none; }
            }
          </style>
        </head>
        <body>
          <div class="header">
            <h1>糖尿病视网膜病变诊断报告</h1>
            <p>患者姓名: ${report.patientName || '未知'} | 患者ID: ${report.patientId}</p>
            <p>报告生成时间: ${formatDate(report.createdAt)}</p>
          </div>
          
          <div class="report">
            <div class="report-header">
              <h3>诊断信息</h3>
              <span class="diagnosis-level ${report.finalDiagnosis}">${getDiagnosisName(report.finalDiagnosis)}</span>
            </div>
            
            <div class="patient-info">
              <strong>患者ID:</strong> ${report.patientId}<br>
              <strong>患者姓名:</strong> ${report.patientName || '未提供'}<br>
              <strong>诊断日期:</strong> ${formatDate(report.createdAt)}
            </div>
            
            <div class="diagnosis">
              <h4>最终诊断结果</h4>
              <p><strong>诊断级别:</strong> ${getDiagnosisName(report.finalDiagnosis)}</p>
            </div>
            
            <div class="summary">
              <h4>临床摘要</h4>
              <p>${report.clinicalSummary || '未提供临床摘要'}</p>
            </div>
            
            ${report.imageUrl ? `
            <div class="image-section">
              <h4>眼底图像</h4>
              <img src="${report.imageUrl}" alt="眼底图像" onerror="this.style.display='none'">
            </div>
            ` : ''}
          </div>
          
          <div class="footer">
            <p>本报告由AI辅助诊断系统生成，仅供临床参考</p>
            <p>生成时间: ${new Date().toLocaleString('zh-CN')}</p>
          </div>
          
          <script>
            window.onload = function() {
              window.print();
              setTimeout(() => window.close(), 100);
            };
          </script>
        </body>
        </html>
      `;

      printWindow.document.write(htmlContent);
      printWindow.document.close();
      
      toast.success('正在打开打印窗口...');
    } catch (error) {
      console.error('导出报告失败:', error);
      toast.error('导出报告失败，请重试');
    }
  };

  // 处理排序
  const handleSort = (field: 'created_at' | 'patient_id') => {
    if (sortBy === field) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(field);
      setSortOrder('desc');
    }
  };

  // 获取诊断级别显示名称
  const getDiagnosisLevelName = (level: DiagnosisLevelType): string => {
    const levelMap: Record<DiagnosisLevelType, string> = {
      'NoDR': '无明显视网膜病变',
      'Mild': '轻度非增殖性',
      'Moderate': '中度非增殖性',
      'Severe': '重度非增殖性',
      'Proliferative': '增殖性'
    };
    return levelMap[level];
  };

  return (
    <div className="bg-gray-50 min-h-screen flex flex-col">
      <Navbar />
      <div className="flex flex-1">
        <Sidebar />
        <main className="flex-1 ml-64 p-6">
          <div className="max-w-7xl mx-auto">
            <header className="mb-8">
              <div className="flex justify-between items-center">
                <div>
                  <motion.h1 
                    initial={{ opacity: 0, y: -20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.5 }}
                    className="text-2xl font-bold text-gray-900"
                  >
                    报告列表
                  </motion.h1>
                  <p className="text-gray-600 mt-1">查看和管理所有诊断报告</p>
                </div>
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  className="relative"
                  onClick={() => setShowExportMenu(!showExportMenu)}
                >
                  <div className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
                    <i className="fas fa-download mr-2"></i>
                    导出报告
                  </div>
                  {showExportMenu && (
                    <div ref={exportMenuRef} className="absolute right-0 mt-2 w-48 bg-white rounded-lg shadow-lg border border-gray-200 z-10">
                      <div className="py-2">
                        <button
                          onClick={() => handleExportReports('excel')}
                          className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                        >
                          <i className="fas fa-file-excel mr-2"></i>
                          导出Excel
                        </button>
                        <button
                          onClick={() => handleExportReports('pdf')}
                          className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                        >
                          <i className="fas fa-file-pdf mr-2"></i>
                          导出PDF
                        </button>
                      </div>
                    </div>
                  )}
                </motion.button>
              </div>
            </header>
            
            {/* 搜索和筛选 */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
              className="bg-white rounded-xl shadow-sm p-6 mb-6 border border-gray-200"
            >
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="relative">
                  <i className="fas fa-search absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400"></i>
                  <input
                    type="text"
                    placeholder="搜索患者ID或姓名..."
                    className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                  />
                </div>
                
                <select
                  className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  value={selectedLevel}
                  onChange={(e) => setSelectedLevel(e.target.value as DiagnosisLevelType | 'all')}
                >
                  <option value="all">所有诊断级别</option>
                  <option value="NoDR">无明显视网膜病变</option>
                  <option value="Mild">轻度非增殖性</option>
                  <option value="Moderate">中度非增殖性</option>
                  <option value="Severe">重度非增殖性</option>
                  <option value="Proliferative">增殖性</option>
                </select>
                
                <div className="flex items-center space-x-2">
                  <label className="text-sm text-gray-600">排序:</label>
                  <select
                    className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    value={sortBy}
                    onChange={(e) => handleSort(e.target.value as 'created_at' | 'patient_id')}
                  >
                    <option value="created_at">创建时间</option>
                    <option value="patient_id">患者ID</option>
                  </select>
                  <button
                    onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
                    className="px-3 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
                  >
                    <i className={`fas fa-sort-${sortOrder === 'asc' ? 'up' : 'down'}`}></i>
                  </button>
                </div>
                
                <div className="text-sm text-gray-600 flex items-center">
                  <span>共 {filteredReports.length} 条记录</span>
                  <button
                    onClick={loadReports}
                    disabled={isLoading}
                    className="ml-auto px-3 py-1 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50"
                  >
                    {isLoading ? '刷新中...' : '刷新'}
                  </button>
                </div>
              </div>
            </motion.div>
            
            {/* 报告列表 */}
            {isLoading ? (
              <div className="flex items-center justify-center h-64">
                <div className="flex items-center">
                  <i className="fas fa-circle-notch fa-spin text-blue-500 text-2xl mr-3"></i>
                  <span className="text-gray-600">正在加载报告...</span>
                </div>
              </div>
            ) : filteredReports.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {filteredReports.map((report, index) => (
                  <motion.div
                    key={report.id}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.5, delay: 0.1 * index }}
                  >
                    <ReportCard
                      report={report}
                      onClick={() => handleReportClick(report)}
                      onExportPDF={() => handleSingleReportPDFExport(report)}
                    />
                  </motion.div>
                ))}
              </div>
            ) : (
              <div className="text-center py-12">
                <div className="w-24 h-24 mx-auto mb-4 bg-gray-100 rounded-full flex items-center justify-center">
                  <i className="fas fa-file-medical text-3xl text-gray-400"></i>
                </div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">暂无报告</h3>
                <p className="text-gray-500 mb-4">
                  {searchTerm || selectedLevel !== 'all' ? '没有找到符合条件的报告' : '还没有生成任何诊断报告'}
                </p>
                {(searchTerm || selectedLevel !== 'all') && (
                  <button
                    onClick={() => {
                      setSearchTerm('');
                      setSelectedLevel('all');
                    }}
                    className="text-blue-600 hover:text-blue-800"
                  >
                    清除筛选条件
                  </button>
                )}
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
