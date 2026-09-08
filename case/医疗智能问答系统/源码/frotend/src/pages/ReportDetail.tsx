import { useContext, useState, useEffect } from 'react';
import { AuthContext } from '../contexts/authContext';
import { useNavigate, useParams } from 'react-router-dom';
import Navbar from '../components/Navbar';
import Sidebar from '../components/Sidebar';
import DiagnosisLevel from '../components/DiagnosisLevel';
import { motion } from 'framer-motion';
import { DiagnosisLevel as DiagnosisLevelType } from '../types';
import { toast } from 'sonner';
import { imageAnalysisAPI, reportsAPI, buildFileUrl } from '../services/api';

export default function ReportDetail() {
  const { user } = useContext(AuthContext);
  const navigate = useNavigate();
  const { id } = useParams();
  interface ReportDetailData {
    id: string;
    patientId: string;
    patientName?: string;
    finalDiagnosis: DiagnosisLevelType;
    imageUrl: string;
    createdAt: string;
    clinicalSummary: string;
    confidence?: number;
    recommendations?: string;
    primaryRecommendations?: string[];
    followUpPlan?: string;
    lifestyleAdvice?: string[];
    monitoringSchedule?: string;
    analysisResults: {
      model: string;
      details: Record<string, unknown>;
    }[];
  }

  const [report, setReport] = useState<ReportDetailData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showFullscreenImage, setShowFullscreenImage] = useState(false);

  useEffect(() => {
    loadReport();
  }, [id]);

  const loadReport = async () => {
    try {
      setIsLoading(true);
      if (!id) {
        throw new Error('报告ID不存在');
      }

      // 获取报告详情
      const response = await reportsAPI.getReportDetail(id);
      const reportData = response.data?.report;

      if (!reportData) {
        throw new Error('报告不存在');
      }

      const levelMap: Record<number, DiagnosisLevelType> = {
        0: 'NoDR',
        1: 'Mild',
        2: 'Moderate',
        3: 'Severe',
        4: 'Proliferative'
      };

      const analysisResults = (reportData.analysis_results || []).map((result: any) => ({
        model: result.model_name || '',
        details: {
          prediction_level: result.prediction_level,
          confidence_score: result.confidence_score,
          processing_time: result.processing_time,
          image_quality: result.image_quality,
          created_at: result.created_at
        }
      }));

      const recommendationsData = reportData.recommendations || {};
      const primaryRecommendations = Array.isArray(recommendationsData.primary_recommendations)
        ? recommendationsData.primary_recommendations
        : [];
      const followUpPlan = recommendationsData.follow_up_plan || '';
      const lifestyleAdvice = Array.isArray(recommendationsData.lifestyle_advice)
        ? recommendationsData.lifestyle_advice
        : [];
      const monitoringSchedule = recommendationsData.monitoring_schedule || '';

      const transformedReport: ReportDetailData = {
        id: reportData.id,
        patientId: reportData.patient_id,
        patientName: reportData.patient_name || '',
        finalDiagnosis: levelMap[reportData.ensemble_diagnosis_level as number] ?? 'NoDR',
        createdAt: reportData.created_at,
        imageUrl: buildFileUrl(reportData.original_image_url),
        clinicalSummary: reportData.report_content?.clinical_summary || '',
        confidence: reportData.ensemble_confidence,
        recommendations: primaryRecommendations.length > 0
          ? primaryRecommendations.join('；')
          : '',
        primaryRecommendations,
        followUpPlan,
        lifestyleAdvice,
        monitoringSchedule,
        analysisResults
      };

      setReport(transformedReport);
    } catch (error) {
      console.error('加载报告失败:', error);
      toast.error('加载报告失败，请刷新重试');
      // 延迟导航回报告列表
      setTimeout(() => {
        navigate('/reports');
      }, 1500);
    } finally {
      setIsLoading(false);
    }
  };

  const handlePrint = async () => {
    try {
      if (!report) {
        toast.error('报告数据不存在');
        return;
      }

      // 生成打印窗口
      const printWindow = window.open('', '_blank', 'width=800,height=600');
      if (!printWindow) {
        toast.error('无法打开打印窗口，请检查浏览器设置');
        return;
      }

      const printContent = `
        <!DOCTYPE html>
        <html>
        <head>
          <title>医疗影像分析报告</title>
          <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .header { text-align: center; border-bottom: 2px solid #333; padding-bottom: 10px; }
            .section { margin: 20px 0; }
            .section h3 { color: #333; border-bottom: 1px solid #ccc; padding-bottom: 5px; }
            .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
            .image-container { text-align: center; }
            .image-container img { max-width: 100%; height: auto; border: 1px solid #ddd; }
            .diagnosis { background: #f8f9fa; padding: 10px; border-radius: 5px; }
            table { width: 100%; border-collapse: collapse; margin: 10px 0; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; }
          </style>
        </head>
        <body>
          <div class="header">
            <h1>医疗影像分析报告</h1>
            <p>报告ID: ${report.id}</p>
            <p>生成时间: ${new Date(report.createdAt).toLocaleString('zh-CN')}</p>
          </div>

          <div class="section">
            <h3>患者信息</h3>
            <div class="info-grid">
              <p><strong>患者ID:</strong> ${report.patientId}</p>
              <p><strong>患者姓名:</strong> ${report.patientName}</p>
            </div>
          </div>

          <div class="section">
            <h3>诊断结果</h3>
            <div class="diagnosis">
              <p><strong>最终诊断:</strong> ${getDiagnosisLevelName(report.finalDiagnosis)}</p>
              ${typeof report.confidence === 'number' ? `<p><strong>置信度:</strong> ${(report.confidence * 100).toFixed(1)}%</p>` : ''}
            </div>
          </div>

          <div class="section">
            <h3>眼底图像</h3>
            <div class="image-container">
              ${report.imageUrl ? `<img src="${report.imageUrl}" alt="眼底图像" />` : '<p>无图像数据</p>'}
            </div>
          </div>

          <div class="section">
            <h3>临床摘要</h3>
            <p>${report.clinicalSummary || '无临床摘要'}</p>
          </div>

          ${report.recommendations ? `
          <div class="section">
            <h3>建议</h3>
            <p>${report.recommendations}</p>
          </div>
          ` : ''}

          <div class="section">
            <h3>详细分析结果</h3>
            ${report.analysisResults && report.analysisResults.length > 0 ? 
              report.analysisResults.map(result => `
                <h4>${result.model}</h4>
                <table>
                  <tr><th>指标</th><th>值</th></tr>
                  ${Object.entries(result.details || {}).map(([key, value]) => 
                    `<tr><td>${key}</td><td>${String(value)}</td></tr>`
                  ).join('')}
                </table>
              `).join('') : '<p>无详细分析结果</p>'
            }
          </div>

          <div style="margin-top: 50px; text-align: center; font-size: 12px; color: #666;">
            <p>此报告由AI医疗影像分析系统生成</p>
          </div>
        </body>
        </html>
      `;

      printWindow.document.write(printContent);
      printWindow.document.close();
      
      // 等待图片加载完成后打印
      setTimeout(() => {
        printWindow.focus();
        printWindow.print();
        printWindow.close();
      }, 500);

    } catch (error) {
      console.error('打印报告失败:', error);
      toast.error('打印报告失败，请重试');
    }
  };

  const getDiagnosisLevelName = (level: DiagnosisLevelType) => {
    const levelMap: Record<DiagnosisLevelType, string> = {
      NoDR: '无糖尿病视网膜病变',
      Mild: '轻度非增殖性糖尿病视网膜病变',
      Moderate: '中度非增殖性糖尿病视网膜病变',
      Severe: '重度非增殖性糖尿病视网膜病变',
      Proliferative: '增殖性糖尿病视网膜病变'
    };
    return levelMap[level] || '未知';
  };

  const handleExport = async () => {
    try {
      if (!report) {
        toast.error('报告数据不存在');
        return;
      }

      const response = await reportsAPI.exportReport(report.id, 'pdf');
      
      if (response.success) {
        // 打开新窗口显示PDF内容
        const printWindow = window.open('', '_blank', 'width=800,height=600');
        if (!printWindow) {
          toast.error('无法打开导出窗口，请检查浏览器设置');
          return;
        }

        printWindow.document.write(response.data);
        printWindow.document.close();

        // 等待内容加载完成后自动打印
        setTimeout(() => {
          printWindow.focus();
          printWindow.print();
          // 不自动关闭窗口，让用户可以保存
        }, 500);

        toast.success('报告导出成功');
      } else {
        throw new Error(response.message || '导出失败');
      }
    } catch (error) {
      console.error('导出报告失败:', error);
      toast.error('导出报告失败，请重试');
    }
  };

  const handleDelete = async () => {
    if (!report) return;
    
    if (window.confirm('确定要删除此报告吗？此操作无法撤销。')) {
      try {
        await imageAnalysisAPI.deleteAnalysis(report.id);
        toast.success('报告已删除');
        setTimeout(() => {
          navigate('/reports');
        }, 1500);
      } catch (error) {
        console.error('删除报告失败:', error);
        toast.error('删除报告失败，请重试');
      }
    }
  };

  if (isLoading) {
    return (
      <div className="bg-gray-50 min-h-screen flex flex-col">
        <Navbar />
        <div className="flex flex-1">
          <Sidebar />
          <main className="flex-1 ml-64 p-6 flex items-center justify-center">
            <div className="text-center">
              <div className="w-16 h-16 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin mx-auto"></div>
              <p className="mt-4 text-gray-600">加载报告中...</p>
            </div>
          </main>
        </div>
      </div>
    );
  }

  if (!report) {
    return null; // 报告不存在，已经在useEffect中处理
  }

  return (
    <div className="bg-gray-50 min-h-screen flex flex-col">
      <Navbar />
      <div className="flex flex-1">
        <Sidebar />
        <main className="flex-1 ml-64 p-6">
          <div className="max-w-6xl mx-auto">
            <motion.header 
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="mb-8"
            >
              <div className="flex flex-col md:flex-row md:justify-between md:items-center">
                <div>
                  <h1 className="text-2xl font-bold text-gray-900">报告详情</h1>
                  <p className="text-gray-600 mt-1">患者ID: {report.patientId}</p>
                </div>
                <div className="flex space-x-3 mt-4 md:mt-0">
                  <motion.button
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    onClick={handlePrint}
                    className="px-4 py-2 bg-white border border-gray-300 rounded-lg font-medium text-gray-700 hover:bg-gray-50 transition-colors flex items-center"
                  >
                    <i className="fas fa-print mr-2"></i>
                    打印
                  </motion.button>
                  <motion.button
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    onClick={handleExport}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors flex items-center"
                  >
                    <i className="fas fa-file-export mr-2"></i>
                    导出
                  </motion.button>
                  <motion.button
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    onClick={handleDelete}
                    className="px-4 py-2 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 transition-colors flex items-center"
                  >
                    <i className="fas fa-trash-alt mr-2"></i>
                    删除
                  </motion.button>
                </div>
              </div>
            </motion.header>
            
            {/* 报告内容 */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
              {/* 左侧：患者信息和图像 */}
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.5, delay: 0.1 }}
                className="lg:col-span-1 space-y-6"
              >
                <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-200">
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">患者信息</h3>
                  <div className="space-y-3">
                    <div>
                      <p className="text-sm text-gray-500">患者ID</p>
                      <p className="font-medium text-gray-900">{report.patientId}</p>
                    </div>
                    {report.patientName && (
                      <div>
                        <p className="text-sm text-gray-500">患者姓名</p>
                        <p className="font-medium text-gray-900">{report.patientName}</p>
                      </div>
                    )}
                    <div>
                      <p className="text-sm text-gray-500">创建时间</p>
                      <p className="font-medium text-gray-900">
                        {new Date(report.createdAt).toLocaleString('zh-CN', {
                          year: 'numeric',
                          month: '2-digit',
                          day: '2-digit',
                          hour: '2-digit',
                          minute: '2-digit'
                        })}
                      </p>
                    </div>
                    <div>
                      <p className="text-sm text-gray-500">创建医生</p>
                      <p className="font-medium text-gray-900">
                        {user?.name || '未知医生'}
                      </p>
                    </div>
                  </div>
                </div>
                
                <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-200">
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">眼底图像</h3>
                  <div 
                    className="border border-gray-200 rounded-lg overflow-hidden cursor-pointer"
                    onClick={() => setShowFullscreenImage(true)}
                  >
                    <img 
                      src={report.imageUrl} 
                      alt="眼底图像" 
                      className="w-full h-auto hover:opacity-90 transition-opacity"
                      onError={(e) => {
                        const target = e.target as HTMLImageElement;
                        target.style.display = 'none';
                        target.nextElementSibling?.classList.remove('hidden');
                      }}
                    />
                    <div className="hidden p-8 text-center text-gray-500">
                      <i className="fas fa-image text-4xl mb-2"></i>
                      <p>图像加载失败</p>
                    </div>
                  </div>
                  <p className="text-center text-sm text-gray-500 mt-2">点击图像查看大图</p>
                </div>
                
                <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-200">
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">诊断结果</h3>
                  <div className="flex justify-center mb-4">
                    <DiagnosisLevel level={report.finalDiagnosis} size="large" />
                  </div>
                  <div className="text-center">
                    <p className="text-sm text-gray-500 mb-1">分析模型数量</p>
                    <p className="text-2xl font-bold text-blue-600">
                      {report.analysisResults?.length || 0}
                    </p>
                  </div>
                </div>
              </motion.div>
              
              {/* 右侧：详细分析结果 */}
              <motion.div
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.5, delay: 0.2 }}
                className="lg:col-span-2 space-y-6"
              >
                {/* 最终诊断 */}
                <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-200">
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">最终诊断</h3>
                  <div className="flex items-center space-x-4">
                    <DiagnosisLevel level={report.finalDiagnosis} size="large" />
                    <div>
                      <h4 className="text-xl font-bold text-gray-900 mb-2">
                        {report.finalDiagnosis === 'NoDR' && '无明显视网膜病变'}
                        {report.finalDiagnosis === 'Mild' && '轻度非增殖性'}
                        {report.finalDiagnosis === 'Moderate' && '中度非增殖性'}
                        {report.finalDiagnosis === 'Severe' && '重度非增殖性'}
                        {report.finalDiagnosis === 'Proliferative' && '增殖性'}
                      </h4>
                      <p className="text-gray-600">
                        基于多模型AI分析的综合诊断结果
                      </p>
                    </div>
                  </div>
                </div>
                
                {/* 临床摘要 */}
                {report.clinicalSummary && (
                  <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-200">
                    <h3 className="text-lg font-semibold text-gray-900 mb-4">临床摘要</h3>
                    <div className="prose max-w-none">
                      <p className="text-gray-700 leading-relaxed">{report.clinicalSummary}</p>
                    </div>
                  </div>
                )}
                
                {(report.primaryRecommendations && report.primaryRecommendations.length > 0) ||
                report.followUpPlan ||
                (report.lifestyleAdvice && report.lifestyleAdvice.length > 0) ||
                report.monitoringSchedule ? (
                  <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-200">
                    <h3 className="text-lg font-semibold text-gray-900 mb-4">随访与建议</h3>
                    {report.primaryRecommendations && report.primaryRecommendations.length > 0 && (
                      <div className="mb-4">
                        <h4 className="text-md font-semibold text-gray-800 mb-2">主要建议</h4>
                        <ul className="list-disc list-inside space-y-1 text-gray-700">
                          {report.primaryRecommendations.map((item, index) => (
                            <li key={index}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {report.followUpPlan && (
                      <div className="mb-4">
                        <h4 className="text-md font-semibold text-gray-800 mb-2">随访计划</h4>
                        <p className="text-gray-700 leading-relaxed">{report.followUpPlan}</p>
                      </div>
                    )}
                    {report.lifestyleAdvice && report.lifestyleAdvice.length > 0 && (
                      <div className="mb-4">
                        <h4 className="text-md font-semibold text-gray-800 mb-2">生活方式建议</h4>
                        <ul className="list-disc list-inside space-y-1 text-gray-700">
                          {report.lifestyleAdvice.map((item, index) => (
                            <li key={index}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {report.monitoringSchedule && (
                      <div>
                        <h4 className="text-md font-semibold text-gray-800 mb-2">监测安排</h4>
                        <p className="text-gray-700 leading-relaxed">{report.monitoringSchedule}</p>
                      </div>
                    )}
                  </div>
                ) : null}
                
                {/* 模型分析结果 */}
                {report.analysisResults && report.analysisResults.length > 0 && (
                  <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-200">
                    <h3 className="text-lg font-semibold text-gray-900 mb-4">AI模型分析结果</h3>
                    <div className="space-y-4">
                      {report.analysisResults.map((result, index) => (
                        <div key={result.model || index} className="border border-gray-200 rounded-lg p-4">
                          <div className="flex justify-between items-center mb-3">
                            <h4 className="font-semibold text-gray-900">{result.model || '未命名模型'}</h4>
                          </div>
                          <div className="text-sm text-gray-600">
                            <p className="mb-2">详细指标:</p>
                            <ul className="list-disc list-inside space-y-1">
                              {Object.entries(result.details || {}).map(([key, value]) => (
                                <li key={key}>
                                  <span className="font-medium mr-1">{key}:</span>
                                  <span>{String(value)}</span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </motion.div>
            </div>
          </div>
        </main>
      </div>
      
      {/* 全屏图像模态框 */}
      {showFullscreenImage && (
        <div 
          className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50"
          onClick={() => setShowFullscreenImage(false)}
        >
          <div className="max-w-4xl max-h-4xl p-4">
            <img 
              src={report.imageUrl} 
              alt="眼底图像" 
              className="max-w-full max-h-full object-contain"
              onClick={(e) => e.stopPropagation()}
            />
            <button
              onClick={() => setShowFullscreenImage(false)}
              className="absolute top-4 right-4 text-white text-2xl hover:text-gray-300"
            >
              <i className="fas fa-times"></i>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
