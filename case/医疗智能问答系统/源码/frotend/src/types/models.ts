/**
 * 模型配置类型定义
 */

export enum ModelType {
  CHAT = 'chat',
  EMBEDDING = 'embedding'
}

export interface ModelConfig {
  id: string;
  name: string;
  provider: string;
  type: ModelType;
  modelName: string;
  apiKey?: string;
  apiEndpoint?: string;
  temperature?: number;
  maxTokens?: number;
  topP?: number;
  systemPrompt?: string;
  status: 'active' | 'inactive' | 'error' | 'testing';
  isDefault: boolean;
  createdAt?: string;
  updatedAt?: string;
  description?: string;
}