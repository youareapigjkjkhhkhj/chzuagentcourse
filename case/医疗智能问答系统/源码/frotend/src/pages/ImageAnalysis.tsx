import { useContext, useState, useRef, useEffect } from 'react';
import { AuthContext } from '../contexts/authContext';
import Navbar from '../components/Navbar';
import Sidebar from '../components/Sidebar';
import { motion } from 'framer-motion';
import { toast } from 'sonner';
import DiagnosisLevel from '../components/DiagnosisLevel';
import { AIModel, AnalysisResult, DiagnosisLevel as DiagnosisLevelType } from '../types';
import ModelCard from '../components/ModelCard';
import { imageAnalysisAPI, reportsAPI } from '../services/api';

interface ModelInfo {
  id: string;
  name: string;
  modelName: string;
  provider: string;
  type: string;
  status: string;
  isDefault: boolean;
  description: string;
  createdAt?: string;
  updatedAt?: string;
}

interface AnalysisHistory {
  id: string;
  patient_id: string;
  patient_name: string;
  image_url: string;
  created_at: string;
  models_used: string[];
  final_diagnosis: DiagnosisLevelType;
  status: 'completed' | 'processing' | 'failed';
  results: AnalysisResult[];
}

export default function ImageAnalysis() {
  const { user } = useContext(AuthContext);
  const [patientId, setPatientId] = useState('');
  const [patientName, setPatientName] = useState('');
  const [selectedImage, setSelectedImage] = useState<string | null>(null);
  const [selectedImageFile, setSelectedImageFile] = useState<File | null>(null);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisResults, setAnalysisResults] = useState<AnalysisResult[]>([]);
  const [showFullscreenImage, setShowFullscreenImage] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [finalDiagnosisLevel, setFinalDiagnosisLevel] = useState<DiagnosisLevelType>('NoDR');
  
  // 处理文件上传
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    
    // 检查文件类型
    const validTypes = ['image/jpeg', 'image/png', 'image/jpg'];
    if (!validTypes.includes(file.type)) {
      toast.error('请上传JPG、JPEG或PNG格式的图像');
      return;
    }
    
    // 检查文件大小（限制为10MB）
    if (file.size > 10 * 1024 * 1024) {
      toast.error('图像文件大小不能超过10MB');
      return;
    }
    
    // 保存文件对象
    setSelectedImageFile(file);
    
    // 读取文件并显示预览
    const reader = new FileReader();
    reader.onload = (event) => {
      setSelectedImage(event.target?.result as string);
    };
    reader.readAsDataURL(file);
    
    toast.success('图像上传成功');
  };
  
  // 处理拖拽上传
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };
  
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file) {
      // 触发文件输入的change事件
      if (fileInputRef.current) {
        const dataTransfer = new DataTransfer();
        dataTransfer.items.add(file);
        fileInputRef.current.files = dataTransfer.files;
        handleFileUpload({
          target: fileInputRef.current
        } as React.ChangeEvent<HTMLInputElement>);
      }
    }
  };
  
  // 处理模型选择
  const handleModelSelect = (model: string) => {
    setSelectedModels(prev => 
      prev.includes(model)
        ? prev.filter(m => m !== model)
        : [...prev, model]
    );
  };
  
  const [currentAnalysisId, setCurrentAnalysisId] = useState<string | null>(null);
  const [analysisHistory, setAnalysisHistory] = useState<AnalysisHistory[]>([]);
  const [availableModels, setAvailableModels] = useState<ModelInfo[]>([]);
  
  // 初始化加载可用模型和分析历史
  useEffect(() => {
    loadAvailableModels();
    loadAnalysisHistory();
  }, []);
  
  const loadAvailableModels = async () => {
    try {
      const response = await imageAnalysisAPI.getAvailableModels();
      const models = response.data?.models || [];
      setAvailableModels(models);

      if (models.length > 0 && selectedModels.length === 0) {
        const defaultModels = models
          .filter((m: ModelInfo) => m.isDefault)
          .map((m: ModelInfo) => m.modelName);
        if (defaultModels.length > 0) {
          setSelectedModels(defaultModels);
        } else {
          setSelectedModels([models[0].modelName]);
        }
      }
    } catch (error) {
      console.error('加载模型列表失败:', error);
      toast.error('加载模型列表失败');
    }
  };
  
  const loadAnalysisHistory = async () => {
    try {
      const response = await imageAnalysisAPI.getAnalysisHistory();
      setAnalysisHistory(response.histories || []);
    } catch (error) {
      console.error('加载分析历史失败:', error);
    }
  };
  
  // 开始分析
  const startAnalysis = async () => {
    // 验证表单
    if (!patientId.trim()) {
      toast.error('请输入患者ID');
      return;
    }
    
    if (!selectedImage) {
      toast.error('请上传眼底图像');
      return;
    }
    
    if (selectedModels.length === 0) {
      toast.error('请至少选择一个AI模型');
      return;
    }
    
    setIsAnalyzing(true);
    setAnalysisResults([]);
    
    try {
      // 创建FormData并上传图像
      const fileInput = fileInputRef.current;
      if (!fileInput?.files?.[0]) {
        throw new Error('未找到图像文件');
      }
      
      const formData = new FormData();
      formData.append('image', fileInput.files[0]);
      formData.append('patient_id', patientId);
      if (patientName.trim()) {
        formData.append('patient_name', patientName.trim());
      }
      
      // 处理模型选择逻辑
      if (selectedModels.length === 1) {
        formData.append('model_type', selectedModels[0]);
      } else if (selectedModels.length > 1) {
        formData.append('model_type', 'ensemble');
        formData.append('selected_models', JSON.stringify(selectedModels));
      } else {
        formData.append('model_type', 'ensemble');
      }
      
      // 开始分析
      const analysisResponse = await imageAnalysisAPI.startAnalysis(formData);
      const analysisId = analysisResponse.data?.analysis_id;
      setCurrentAnalysisId(analysisId);
      
      toast.success('分析已开始，正在处理中...');
      
      // 轮询分析状态
      pollAnalysisStatus(analysisId);
      
    } catch (error) {
      console.error('分析失败:', error);
      toast.error('分析失败，请重试');
      setIsAnalyzing(false);
    }
  };
  
  const pollAnalysisStatus = async (analysisId: string) => {
    try {
      const checkStatus = async () => {
        try {
          const response = await imageAnalysisAPI.getAnalysisStatus(analysisId);
          
          if (response.data?.status === 'completed') {
            const resultsResponse = await imageAnalysisAPI.getAnalysisResults(analysisId);
            
            const rawResults = resultsResponse.data?.analysis_results || [];
            const levelMap: Record<number, DiagnosisLevelType> = {
              0: 'NoDR',
              1: 'Mild',
              2: 'Moderate',
              3: 'Severe',
              4: 'Proliferative'
            };
            
            const transformedResults: AnalysisResult[] = rawResults.map((result: any) => ({
              model: (result.model_name || 'ResNet') as AIModel,
              level: levelMap[result.prediction_level as number] ?? 'NoDR',
              confidence: result.confidence_score || 0,
              features: result.model_prediction?.features || [],
              analysisTime: result.created_at || new Date().toISOString()
            }));
            
            setAnalysisResults(transformedResults);

            const backendFinal = resultsResponse.data?.final_diagnosis;
            if (backendFinal && typeof backendFinal.level === 'number') {
              const mappedLevel = levelMap[backendFinal.level as number] ?? 'NoDR';
              setFinalDiagnosisLevel(mappedLevel);
            } else {
              if (transformedResults.length > 0) {
                let maxSeverity = 0;
                let tempFinal: DiagnosisLevelType = 'NoDR';
                const severityMap: Record<DiagnosisLevelType, number> = {
                  NoDR: 0,
                  Mild: 1,
                  Moderate: 2,
                  Severe: 3,
                  Proliferative: 4
                };
                transformedResults.forEach(r => {
                  const severity = severityMap[r.level];
                  if (severity > maxSeverity) {
                    maxSeverity = severity;
                    tempFinal = r.level;
                  }
                });
                setFinalDiagnosisLevel(tempFinal);
              } else {
                setFinalDiagnosisLevel('NoDR');
              }
            }
            setIsAnalyzing(false);
            toast.success('AI分析完成');
            
            // 刷新历史记录
            loadAnalysisHistory();
          } else if (response.data?.status === 'failed') {
            setIsAnalyzing(false);
            setCurrentAnalysisId(null);
            toast.error('分析失败，请重试');
          } else {
            // 继续轮询
            setTimeout(checkStatus, 2000);
          }
        } catch (error) {
          console.error('获取分析状态失败:', error);
          setIsAnalyzing(false);
          setCurrentAnalysisId(null);
          toast.error('获取分析状态失败');
        }
      };
      
      checkStatus();
    } catch (error) {
      console.error('轮询分析状态失败:', error);
      setIsAnalyzing(false);
      setCurrentAnalysisId(null);
    }
  };
  
  // 保存分析结果
  const saveReport = async () => {
    if (analysisResults.length === 0) {
      toast.error('没有可保存的分析结果');
      return;
    }
    
    if (!patientId) {
      toast.error('请先输入患者ID');
      return;
    }
    
    try {
      if (currentAnalysisId) {
        const levelToNumber: Record<DiagnosisLevelType, number> = {
          NoDR: 0,
          Mild: 1,
          Moderate: 2,
          Severe: 3,
          Proliferative: 4
        };
        const ensembleLevel = levelToNumber[finalDiagnosisLevel] ?? 0;
        const ensembleConfidence = Math.max(...analysisResults.map(r => r.confidence));

        const reportContent = {
          analysis_results: analysisResults,
          final_diagnosis: {
            level: finalDiagnosisLevel,
            confidence: ensembleConfidence,
            description: getDiagnosisLevelName(finalDiagnosisLevel)
          },
          image_info: {
            file_name: selectedImageFile?.name,
            file_size: selectedImageFile?.size
          },
          model_used: analysisResults.map(r => r.model),
          timestamp: new Date().toISOString()
        };
        
        const reportData = {
          analysis_id: currentAnalysisId,
          patient_id: patientId,
          patient_name: patientName || '未提供',
          ensemble_diagnosis_level: ensembleLevel,
          ensemble_confidence: ensembleConfidence,
          analysis_results: analysisResults,
          model_predictions: analysisResults.map(r => ({
            model: r.model,
            level: r.level,
            confidence: r.confidence,
            features: r.features
          })),
          clinical_summary: getDiagnosisLevelName(finalDiagnosisLevel),
          features_detected: analysisResults.flatMap(r => r.features || []),
          primary_recommendations: [generateRecommendations(finalDiagnosisLevel, ensembleConfidence)],
          follow_up_plan: finalDiagnosisLevel === 'NoDR' ? '建议每年进行定期眼科检查' : '建议定期随访，观察病情变化',
          lifestyle_advice: ['保持良好的血糖控制', '定期进行眼科检查', '健康饮食和适量运动'],
          monitoring_schedule: finalDiagnosisLevel === 'NoDR' ? '每年检查一次' : '每3-6个月检查一次'
        };
        
        await reportsAPI.createReport(reportData as any);
        toast.success('报告已保存到数据库');
        
        setPatientId('');
        setPatientName('');
        setSelectedImage(null);
        setSelectedImageFile(null);
        setAnalysisResults([]);
        setFinalDiagnosisLevel('NoDR');
        setCurrentAnalysisId(null);
        
        window.location.reload();
      } else {
        toast.error('当前分析ID不存在，请重新进行分析后再保存报告');
      }
    } catch (error) {
      console.error('保存报告失败:', error);
      toast.error('保存报告失败，请重试');
    }
  };

  // 获取诊断级别名称
  const getDiagnosisLevelName = (level: DiagnosisLevelType): string => {
    const levelNames = {
      'NoDR': '无糖尿病视网膜病变',
      'Mild': '轻度糖尿病视网膜病变',
      'Moderate': '中度糖尿病视网膜病变',
      'Severe': '重度糖尿病视网膜病变',
      'Proliferative': '增殖性糖尿病视网膜病变'
    };
    return levelNames[level] || '未知诊断级别';
  };

  // 生成建议
  const generateRecommendations = (level: DiagnosisLevelType, confidence: number): string => {
    let recommendations = '';
    
    switch (level) {
      case 'NoDR':
        recommendations = '建议每年进行定期眼科检查，保持良好的血糖控制。';
        break;
      case 'Mild':
        recommendations = '建议每6个月进行一次眼底检查，严格控制血糖，定期随访。';
        break;
      case 'Moderate':
        recommendations = '建议每3-4个月进行一次眼底检查，加强血糖管理，必要时考虑激光治疗。';
        break;
      case 'Severe':
        recommendations = '建议立即进行眼科专科治疗，考虑激光光凝或玻璃体腔注射治疗。';
        break;
      case 'Proliferative':
        recommendations = '建议立即进行眼科急诊处理，可能需要玻璃体切割手术等积极治疗。';
        break;
      default:
        recommendations = '建议咨询眼科专科医生进行进一步评估。';
    }
    
    if (confidence < 0.8) {
      recommendations += ' 注意：模型预测置信度较低，建议人工复核。';
    }
    
    return recommendations;
  };
  
  const getModelFeatures = (modelName: string): string => {
    const model = availableModels.find(m => m.modelName === modelName);
    return model ? model.description || '深度学习模型' : '深度学习模型';
  };
  
  return (
    <div className="bg-gray-50 min-h-screen flex flex-col">
      <Navbar />
      <div className="flex flex-1">
        <Sidebar />
        <main className="flex-1 ml-64 p-6">
          <div className="max-w-7xl mx-auto">
            <motion.header 
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="mb-8"
            >
              <h1 className="text-2xl font-bold text-gray-900">图像分析</h1>
              <p className="text-gray-600 mt-1">上传眼底图像并进行AI辅助诊断</p>
            </motion.header>
            
            {/* 主要内容区域 */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* 左侧：患者信息和图像上传 */}
              <div className="lg:col-span-1 space-y-6">
                <motion.div
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.5, delay: 0.1 }}
                  className="bg-white rounded-xl shadow-sm p-6 border border-gray-200"
                >
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">患者信息</h3>
                  <div className="space-y-4">
                    <div>
                      <label htmlFor="patientId" className="block text-sm font-medium text-gray-700 mb-1">
                        患者ID <span className="text-red-500">*</span>
                      </label>
                      <input
                        type="text"
                        id="patientId"
                        value={patientId}
                        onChange={(e) => setPatientId(e.target.value)}
                        className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all"
                        placeholder="输入患者ID"
                      />
                    </div>
                    <div>
                      <label htmlFor="patientName" className="block text-sm font-medium text-gray-700 mb-1">
                        患者姓名
                      </label>
                      <input
                        type="text"
                        id="patientName"
                        value={patientName}
                        onChange={(e) => setPatientName(e.target.value)}
                        className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all"
                        placeholder="输入患者姓名（可选）"
                      />
                    </div>
                  </div>
                </motion.div>
                
                <motion.div
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.5, delay: 0.2 }}
                  className="bg-white rounded-xl shadow-sm p-6 border border-gray-200"
                >
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">图像上传</h3>
                  
                  {/* 隐藏的文件输入 */}
                  <input
                    type="file"
                    ref={fileInputRef}
                    accept="image/jpeg, image/jpg, image/png"
                    onChange={handleFileUpload}
                    className="hidden"
                  />
                  
                  {/* 图像预览区域 */}
                  {!selectedImage ? (
                    <div 
                      className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center cursor-pointer hover:bg-gray-50 transition-colors"
                      onClick={() => fileInputRef.current?.click()}
                      onDragOver={handleDragOver}
                      onDrop={handleDrop}
                    >
                      <div className="w-16 h-16 bg-blue-50 rounded-full flex items-center justify-center mx-auto mb-4">
                        <i className="fas fa-cloud-upload-alt text-blue-500 text-2xl"></i>
                      </div>
                      <p className="text-gray-700 font-medium">点击或拖拽上传眼底图像</p>
                      <p className="text-gray-500 text-sm mt-1">支持 JPG、JPEG、PNG 格式，最大 10MB</p>
                    </div>
                  ) : (
                    <div className="relative">
                      <div 
                        className="border border-gray-200 rounded-lg overflow-hidden"
                        onClick={() => setShowFullscreenImage(true)}
                      >
                        <img 
                          src={selectedImage} 
                          alt="眼底图像" 
                          className="w-full h-auto cursor-pointer hover:opacity-90 transition-opacity"
                        />
                      </div>
                      <button 
                        className="absolute top-2 right-2 w-8 h-8 bg-red-500 rounded-full flex items-center justify-center text-white hover:bg-red-600 transition-colors"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedImage(null);
                          if (fileInputRef.current) {
                            fileInputRef.current.value = '';
                          }
                        }}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                      <p className="text-center text-sm text-gray-500 mt-2">点击图像查看大图</p>
                    </div>
                  )}
                </motion.div>
                
                <motion.div
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.5, delay: 0.3 }}
                  className="bg-white rounded-xl shadow-sm p-6 border border-gray-200"
                >
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">AI模型选择</h3>
                  <div className="space-y-3">
                    {availableModels.length > 0 ? (
                      availableModels.filter(model => model.status === 'active').map((modelData) => (
                        <div 
                          key={modelData.id}
                          className={`flex items-center p-3 border rounded-lg cursor-pointer transition-all ${
                            selectedModels.includes(modelData.modelName)
                              ? 'border-blue-500 bg-blue-50'
                              : 'border-gray-200 hover:border-gray-300'
                          }`}
                          onClick={() => handleModelSelect(modelData.modelName)}
                        >
                          <input
                            type="checkbox"
                            checked={selectedModels.includes(modelData.modelName)}
                            onChange={() => {}}
                            className="w-4 h-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                            readOnly
                          />
                          <div className="ml-3">
                            <div className="flex items-center">
                              <span className="font-medium text-gray-900">{modelData.name}</span>
                              <span className="ml-2 text-xs text-gray-500">
                                类型: {modelData.type}
                              </span>
                            </div>
                            <p className="text-xs text-gray-500 mt-1">{modelData.description || '深度学习模型'}</p>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="text-center text-gray-500 py-4">
                        正在加载模型信息...
                      </div>
                    )}
                  </div>
                </motion.div>
              </div>
              
              {/* 右侧：分析结果 */}
              <div className="lg:col-span-2">
                <motion.div
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.5, delay: 0.4 }}
                  className="bg-white rounded-xl shadow-sm p-6 border border-gray-200 mb-6"
                >
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">分析控制</h3>
                  
                  <div className="flex flex-col sm:flex-row space-y-4 sm:space-y-0 sm:space-x-4">
                    <motion.button
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                      onClick={startAnalysis}
                      disabled={isAnalyzing || !selectedImage || selectedModels.length === 0}
                      className={`flex-1 py-3 px-4 bg-blue-600 text-white rounded-lg font-medium transition-colors flex items-center justify-center ${
                        isAnalyzing || !selectedImage || selectedModels.length === 0
                          ? 'opacity-70 cursor-not-allowed'
                          : 'hover:bg-blue-700'
                      }`}
                    >
                      {isAnalyzing ? (
                        <div className="flex items-center">
                          <i className="fas fa-circle-notch fa-spin mr-2"></i>
                          分析中...
                        </div>
                      ) : (
                        <div className="flex items-center">
                          <i className="fas fa-brain mr-2"></i>
                          开始AI分析
                        </div>
                      )}
                    </motion.button>
                    
                    <motion.button
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                      onClick={saveReport}
                      disabled={analysisResults.length === 0}
                      className={`flex-1 py-3 px-4 bg-green-600 text-white rounded-lg font-medium transition-colors flex items-center justify-center ${
                        analysisResults.length === 0
                          ? 'opacity-70 cursor-not-allowed'
                          : 'hover:bg-green-700'
                      }`}
                    >
                      <i className="fas fa-save mr-2"></i>
                      保存报告
                    </motion.button>
                  </div>
                </motion.div>
                
                {/* 分析结果展示 */}
                {analysisResults.length > 0 && (
                  <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.5, delay: 0.5 }}
                    className="space-y-6"
                  >
                    <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-200">
                      <h3 className="text-lg font-semibold text-gray-900 mb-4">综合诊断结果</h3>
                      
                      <div className="flex items-center justify-between mb-4">
                        <div className="flex items-center">
                          <div className="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center mr-3">
                            <i className="fas fa-stethoscope text-blue-600 text-xl"></i>
                          </div>
                          <div>
                            <h4 className="font-semibold text-gray-900">最终诊断</h4>
                          </div>
                        </div>
                        <DiagnosisLevel level={finalDiagnosisLevel} size="large" />
                      </div>
                      
                      <div className="bg-blue-50 p-4 rounded-lg mb-4">
                        <h4 className="font-semibold text-blue-800 mb-2">临床摘要</h4>
                        <p className="text-blue-700">
                          患者{patientName ? patientName : patientId}眼底检查显示{
                            finalDiagnosisLevel === 'NoDR' ? '未见明显异常' : '存在异常改变'
                          }，建议{finalDiagnosisLevel === 'NoDR' ? '定期随访' : '进一步检查和治疗'}。
                        </p>
                      </div>
                    </div>
                    
                    {/* 各模型分析结果 */}
                    <div className="space-y-4">
                      {analysisResults.map((result, index) => (
                        <motion.div
                          key={result.model}
                          initial={{ opacity: 0, y: 20 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ duration: 0.5, delay: 0.6 + index * 0.1 }}
                          className="bg-white rounded-xl shadow-sm p-6 border border-gray-200"
                        >
                          <div className="flex items-center justify-between mb-4">
                            <div className="flex items-center">
                              <div className={`w-10 h-10 rounded-full flex items-center justify-center mr-3 ${
                                result.model === 'ResNet' ? 'bg-blue-100 text-blue-600' :
                                result.model === 'DenseNet' ? 'bg-green-100 text-green-600' :
                                'bg-purple-100 text-purple-600'
                              }`}>
                                <i className="fas fa-network-wired"></i>
                              </div>
                              <div>
                                <h4 className="font-semibold text-gray-900">{result.model} 分析结果</h4>
                                <p className="text-sm text-gray-500">{getModelFeatures(result.model)}</p>
                              </div>
                            </div>
                            <div className="flex items-center">
                              <div className="bg-gray-100 text-gray-700 px-3 py-1 rounded-full text-sm mr-3">
                                置信度: {(result.confidence * 100).toFixed(1)}%
                              </div>
                              <DiagnosisLevel level={result.level} size="medium" />
                            </div>
                          </div>
                          
                          <div className="mt-4">
                            <h5 className="font-medium text-gray-900 mb-2">识别的病理特征</h5>
                            <div className="space-y-3">
                              {(result.features || []).map(feature => (
                                <div key={feature.id} className="flex items-center bg-gray-50 p-3 rounded-lg">
                                  <div className="w-8 h-8 rounded-full bg-orange-100 flex items-center justify-center mr-3">
                                    <i className="fas fa-virus text-orange-600"></i>
                                  </div>
                                  <div className="flex-1">
                                    <div className="flex items-center">
                                      <h6 className="font-medium text-gray-900">{feature.name}</h6>
                                      <span className="ml-2 text-xs text-gray-500">
                                        置信度: {(feature.confidence * 100).toFixed(1)}%
                                      </span>
                                    </div>
                                    <p className="text-sm text-gray-600">{feature.description}</p>
                                    {feature.location && (
                                      <p className="text-xs text-gray-500 mt-1">
                                        <i className="fas fa-map-marker-alt mr-1"></i>
                                        {feature.location}
                                      </p>
                                    )}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        </motion.div>
                      ))}
                    </div>
                  </motion.div>
                )}
              </div>
            </div>
          </div>
        </main>
      </div>
      
      {/* 全屏图像查看器 */}
      {showFullscreenImage && selectedImage && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black bg-opacity-90 z-50 flex items-center justify-center p-4"
          onClick={() => setShowFullscreenImage(false)}
        >
          <button 
            className="absolute top-4 right-4 w-10 h-10 bg-white bg-opacity-20 rounded-full flex items-center justify-center text-white hover:bg-opacity-30 transition-colors"
          >
            <i className="fas fa-times text-xl"></i>
          </button>
          <img 
            src={selectedImage} 
            alt="眼底图像（全屏）" 
            className="max-w-full max-h-full object-contain"
          />
        </motion.div>
      )}
    </div>
  );
}
