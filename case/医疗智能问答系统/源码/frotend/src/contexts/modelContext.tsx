import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { ModelConfig, ModelProvider, ModelStatus, ModelType, ProviderConfig } from '@/types/model';
import { toast } from 'sonner';
import { modelAPI } from '@/services/api';
import { useAuth } from './authContext';

// 模型提供商配置
const providerConfigs: Record<ModelProvider, ProviderConfig> = {
  [ModelProvider.OPENAI]: {
    name: ModelProvider.OPENAI,
    displayName: 'OpenAI',
    icon: 'fa-brands fa-openai',
    description: 'OpenAI GPT模型，包括GPT-3.5和GPT-4系列',
    requiredFields: ['apiKey', 'apiEndpoint'],
    optionalFields: ['temperature', 'maxTokens'],
    defaultModels: ['gpt-3.5-turbo', 'gpt-4', 'gpt-4-turbo'],
    color: 'green'
  },
  [ModelProvider.OLLAMA]: {
    name: ModelProvider.OLLAMA,
    displayName: 'Ollama',
    icon: 'fa-robot',
    description: '本地运行的开源大语言模型',
    requiredFields: ['apiEndpoint'],
    optionalFields: ['temperature', 'maxTokens'],
    defaultModels: ['llama2', 'codellama', 'mistral'],
    color: 'purple'
  },
  [ModelProvider.QIANWEN]: {
    name: ModelProvider.QIANWEN,
    displayName: '千问',
    icon: 'fa-comments',
    description: '阿里云通义千问大语言模型',
    requiredFields: ['apiKey', 'apiEndpoint'],
    optionalFields: ['temperature', 'maxTokens'],
    defaultModels: ['qwen-turbo', 'qwen-plus', 'qwen-max'],
    color: 'blue'
  }
};

interface ModelContextType {
  models: ModelConfig[];
  loading: boolean;
  addModel: (model: Omit<ModelConfig, 'id' | 'createdAt' | 'updatedAt'>) => Promise<void>;
  updateModel: (id: string, updates: Partial<ModelConfig>) => Promise<void>;
  deleteModel: (id: string) => Promise<void>;
  testModel: (id: string) => Promise<boolean>;
  setDefaultModel: (id: string) => Promise<void>;
  getProviderConfig: (provider: ModelProvider) => ProviderConfig;
  getDefaultModel: () => ModelConfig | null;
}

const ModelContext = createContext<ModelContextType | undefined>(undefined);

// 转换后端模型数据为前端格式
const transformModelFromBackend = (backendModel: any): ModelConfig => {
  // 将后端返回的大写provider转换为小写，以匹配前端枚举
  const providerMap: Record<string, string> = {
    OPENAI: 'openai',
    OLLAMA: 'ollama',
    QIANWEN: 'qianwen',
  };

  return {
    id: backendModel.id?.toString() || '',
    name: backendModel.name,
    provider: providerMap[(backendModel.provider || '').toUpperCase()] || backendModel.provider,
    type: backendModel.type,
    // 后端使用驼峰字段
    modelName: backendModel.modelName,
    apiKey: backendModel.apiKey,
    apiEndpoint: backendModel.apiEndpoint,
    temperature: backendModel.temperature,
    maxTokens: backendModel.maxTokens,
    topP: backendModel.topP,
    systemPrompt: backendModel.systemPrompt,
    status: (backendModel.status || ModelStatus.ACTIVE) as ModelStatus,
    isDefault: backendModel.isDefault,
    createdAt: backendModel.createdAt ? new Date(backendModel.createdAt) : new Date(),
    updatedAt: backendModel.updatedAt ? new Date(backendModel.updatedAt) : new Date(),
    description: backendModel.description,
    parameters: backendModel.parameters,
  };
};

// 转换前端模型数据为后端格式
const transformModelToBackend = (frontendModel: Partial<ModelConfig>) => {
  // 后端路由期望驼峰字段名
  return {
    name: frontendModel.name,
    provider: frontendModel.provider,
    type: frontendModel.type,
    modelName: frontendModel.modelName,
    apiKey: frontendModel.apiKey,
    apiEndpoint: frontendModel.apiEndpoint,
    temperature: frontendModel.temperature,
    maxTokens: frontendModel.maxTokens,
    topP: frontendModel.topP,
    systemPrompt: frontendModel.systemPrompt,
    description: frontendModel.description,
    isDefault: frontendModel.isDefault,
    status: frontendModel.status,
  };
};

export function ModelContextProvider({ children }: { children: ReactNode }) {
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const { isAuthenticated } = useAuth();

  // 初始化时加载所有模型，但仅在用户已登录时
  useEffect(() => {
    if (isAuthenticated) {
      loadModels();
    } else {
      // 如果用户未登录，不加载模型，设置loading为false
      setLoading(false);
    }
  }, [isAuthenticated]);

  // 从后端加载模型
  const loadModels = async () => {
    try {
      setLoading(true);
      const response = await modelAPI.getModels();
      if (response && response.data && response.data.models) {
        const transformedModels = response.data.models.map(transformModelFromBackend);
        setModels(transformedModels);
      }
    } catch (error) {
      console.error('加载模型失败:', error);
      toast.error('加载模型失败');
    } finally {
      setLoading(false);
    }
  };

  // 添加新模型
  const addModel = async (modelData: Omit<ModelConfig, 'id' | 'createdAt' | 'updatedAt'>) => {
    setLoading(true);
    try {
      const backendData = transformModelToBackend(modelData);
      const response = await modelAPI.createModel(backendData);
      
      if (response && response.data && response.data.model) {
        const newModel = transformModelFromBackend(response.data.model);
        setModels(prev => [...prev, newModel]);
        toast.success('模型添加成功');
      }
    } catch (error) {
      console.error('添加模型失败:', error);
      toast.error('添加模型失败');
    } finally {
      setLoading(false);
    }
  };

  // 更新模型
  const updateModel = async (id: string, updates: Partial<ModelConfig>) => {
    setLoading(true);
    try {
      const backendData = transformModelToBackend(updates);
      const response = await modelAPI.updateModel(id, backendData);
      
      if (response && response.data && response.data.model) {
        const updatedModel = transformModelFromBackend(response.data.model);
        setModels(prev => prev.map(model => 
          model.id === id ? updatedModel : model
        ));
        toast.success('模型更新成功');
      }
    } catch (error) {
      console.error('更新模型失败:', error);
      toast.error('更新模型失败');
    } finally {
      setLoading(false);
    }
  };

  // 删除模型
  const deleteModel = async (id: string) => {
    setLoading(true);
    try {
      const modelToDelete = models.find(m => m.id === id);
      if (modelToDelete?.isDefault) {
        toast.error('不能删除默认模型');
        return;
      }
      
      await modelAPI.deleteModel(id);
      setModels(prev => prev.filter(model => model.id !== id));
      toast.success('模型删除成功');
    } catch (error) {
      console.error('删除模型失败:', error);
      toast.error('删除模型失败');
    } finally {
      setLoading(false);
    }
  };

  // 测试模型连接
  const testModel = async (id: string): Promise<boolean> => {
    const model = models.find(m => m.id === id);
    if (!model) return false;
    
    // 先更新状态为测试中
    setModels(prev => prev.map(m => 
      m.id === id 
        ? { ...m, status: ModelStatus.TESTING }
        : m
    ));
    
    try {
      const response = await modelAPI.testModel(id);
      const testSuccess = !!response?.data?.testResult?.success;
      
      if (testSuccess) {
        // 更新模型状态为活跃
        setModels(prev => prev.map(m => 
          m.id === id 
            ? { ...m, status: ModelStatus.ACTIVE }
            : m
        ));
        toast.success('模型连接测试成功');
        return true;
      } else {
        // 更新模型状态为错误
        setModels(prev => prev.map(m => 
          m.id === id 
            ? { ...m, status: ModelStatus.ERROR }
            : m
        ));
        const errMsg = response?.data?.testResult?.errorMessage || '模型连接测试失败';
        toast.error(errMsg);
        return false;
      }
    } catch (error) {
      console.error('测试模型失败:', error);
      
      // 更新模型状态为错误
      setModels(prev => prev.map(m => 
        m.id === id 
          ? { ...m, status: ModelStatus.ERROR }
          : m
      ));
      
      toast.error('模型连接测试失败');
      return false;
    }
  };

  // 设置默认模型
  const setDefaultModel = async (id: string) => {
    try {
      await modelAPI.setDefaultModel(id);
      
      // 更新所有模型的默认状态
      setModels(prev => prev.map(m => ({ 
        ...m, 
        isDefault: m.id === id 
      })));
      toast.success('默认模型设置成功');
    } catch (error) {
      console.error('设置默认模型失败:', error);
      toast.error('设置默认模型失败');
    }
  };

  // 获取提供商配置
  const getProviderConfig = (provider: ModelProvider): ProviderConfig => {
    return providerConfigs[provider];
  };

  // 获取默认模型
  const getDefaultModel = (): ModelConfig | null => {
    return models.find(m => m.isDefault) || null;
  };

  return (
    <ModelContext.Provider
      value={{
        models,
        loading,
        addModel,
        updateModel,
        deleteModel,
        testModel,
        setDefaultModel,
        getProviderConfig,
        getDefaultModel
      }}
    >
      {children}
    </ModelContext.Provider>
  );
}

export function useModel() {
  const context = useContext(ModelContext);
  if (context === undefined) {
    throw new Error('useModel must be used within a ModelProvider');
  }
  return context;
}