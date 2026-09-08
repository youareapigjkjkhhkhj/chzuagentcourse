// 用户信息类型
export interface UserInfo {
  id: string;
  email: string;
  name: string;
  role: 'admin' | 'doctor';
  lastLogin: string;
}

// 诊断级别类型
export type DiagnosisLevel = 'NoDR' | 'Mild' | 'Moderate' | 'Severe' | 'Proliferative';

// AI模型类型
export type AIModel = 'ResNet' | 'DenseNet' | 'EfficientNet';

// 病理特征类型
export interface PathologicalFeature {
  id: string;
  name: string;
  description: string;
  confidence: number;
  location?: string;
}

// AI分析结果类型
export interface AnalysisResult {
  model: AIModel;
  level: DiagnosisLevel;
  confidence: number;
  features: PathologicalFeature[];
  analysisTime: string;
}

// 诊断报告类型
export interface DiagnosisReport {
  id: string;
  patientId: string;
  patientName?: string;
  imageUrl: string;
  analysisResults: AnalysisResult[];
  finalDiagnosis: DiagnosisLevel;
  clinicalSummary: string;
  createdBy: string; // 用户ID
  createdAt: string;
  updatedAt: string;
}

// 系统统计数据类型
export interface SystemStats {
  totalReports: number;
  highRiskCases: number;
  activeUsers: number;
  dailyReports: number;
  diagnosisDistribution: {
    level: DiagnosisLevel;
    count: number;
    percentage: number;
  }[];
  modelPerformance: {
    model: AIModel;
    accuracy: number;
    precision: number;
    recall: number;
    f1Score: number;
  }[];
}

// 用户操作日志类型
export interface OperationLog {
  id: string;
  userId: string;
  userName: string;
  action: string;
  details: string;
  timestamp: string;
  ipAddress: string;
}

// 系统设置类型
export interface SystemSettings {
  diagnosisThresholds: {
    [key in DiagnosisLevel]: number;
  };
  notificationSettings: {
    emailEnabled: boolean;
    pushEnabled: boolean;
    highRiskOnly: boolean;
  };
  storageSettings: {
    autoBackup: boolean;
    retentionPeriod: number; // 天
  };
}

// 获取诊断级别对应的颜色
export const getDiagnosisColor = (level: DiagnosisLevel): string => {
  const colors: Record<DiagnosisLevel, string> = {
    'NoDR': 'bg-green-500',
    'Mild': 'bg-yellow-500',
    'Moderate': 'bg-orange-500',
    'Severe': 'bg-red-500',
    'Proliferative': 'bg-red-700'
  };
  return colors[level];
};

// 获取诊断级别对应的中文名称
export const getDiagnosisName = (level: DiagnosisLevel): string => {
  const names: Record<DiagnosisLevel, string> = {
    'NoDR': '无明显视网膜病变',
    'Mild': '轻度非增殖性',
    'Moderate': '中度非增殖性',
    'Severe': '重度非增殖性',
    'Proliferative': '增殖性'
  };
  return names[level];
};

// 获取诊断级别对应的描述
export const getDiagnosisDescription = (level: DiagnosisLevel): string => {
  const descriptions: Record<DiagnosisLevel, string> = {
    'NoDR': '视网膜正常，无病变迹象',
    'Mild': '轻微病变，仅有微动脉瘤等',
    'Moderate': '中等程度病变，有出血和渗出',
    'Severe': '严重病变，4个象限均有病变',
    'Proliferative': '最严重级别，出现新生血管'
  };
  return descriptions[level];
};

// 获取AI模型的特点
export const getModelFeatures = (model: AIModel): string => {
  const features: Record<AIModel, string> = {
    'ResNet': '深度网络，解决梯度消失问题',
    'DenseNet': '特征重用，参数效率高',
    'EfficientNet': '精确缩放，平衡准确率和计算成本'
  };
  return features[model];
};
// 导出向量化相关类型
export * from './vectorization';
