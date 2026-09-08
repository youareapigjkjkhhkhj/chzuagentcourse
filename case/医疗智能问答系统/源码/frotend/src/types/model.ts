// 模型提供商类型
export enum ModelProvider {
  OPENAI = 'openai',
  OLLAMA = 'ollama',
  QIANWEN = 'qianwen'
}

// 模型类型
export enum ModelType {
  CHAT = 'chat',      // 对话模型
  EMBEDDING = 'embedding'  // 向量模型
}

// 模型状态
export enum ModelStatus {
  ACTIVE = 'active',
  INACTIVE = 'inactive',
  ERROR = 'error',
  TESTING = 'testing'
}

// 模型配置接口
export interface ModelConfig {
  id: string;
  name: string;
  provider: ModelProvider;
  type: ModelType;  // 添加模型类型字段
  modelName: string;
  apiKey?: string;
  apiEndpoint?: string;
  temperature?: number;
  maxTokens?: number;
  topP?: number;
  systemPrompt?: string;
  status: ModelStatus;
  isDefault: boolean;
  createdAt: Date;
  updatedAt: Date;
  description?: string;
  parameters?: Record<string, any>;
}

// 模型测试结果
export interface ModelTestResult {
  success: boolean;
  responseTime?: number;
  errorMessage?: string;
  sampleResponse?: string;
}

// 模型提供商配置
export interface ProviderConfig {
  name: string;
  displayName: string;
  icon: string;
  description: string;
  requiredFields: string[];
  optionalFields: string[];
  defaultModels: string[];
  color: string;
}