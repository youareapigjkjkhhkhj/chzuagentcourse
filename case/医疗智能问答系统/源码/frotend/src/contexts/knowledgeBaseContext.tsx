import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { knowledgeBaseAPI } from '@/services/api';
import { toast } from 'sonner';
import { useAuth } from './authContext';

interface KnowledgeBase {
  id: string;
  name: string;
  description?: string;
  status: 'active' | 'archived';
  documentCount: number;
  vectorCount?: number;
  createdAt: Date;
  updatedAt: Date;
}

interface KnowledgeBaseContextType {
  knowledgeBases: KnowledgeBase[];
  loading: boolean;
  getDefaultKnowledgeBase: () => KnowledgeBase | null;
  loadKnowledgeBases: () => Promise<void>;
}

const KnowledgeBaseContext = createContext<KnowledgeBaseContextType | undefined>(undefined);

export function KnowledgeBaseContextProvider({ children }: { children: ReactNode }) {
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);
  const { isAuthenticated } = useAuth();

  // 初始化时加载所有知识库，但仅在用户已登录时
  useEffect(() => {
    if (isAuthenticated) {
      loadKnowledgeBases();
    } else {
      // 如果用户未登录，不加载知识库，设置loading为false
      setLoading(false);
    }
  }, [isAuthenticated]);

  // 从后端加载知识库
  const loadKnowledgeBases = async () => {
    try {
      setLoading(true);
      const response = await knowledgeBaseAPI.getKnowledgeBases({});
      if (response && response.data && response.data.knowledgeBases) {
        setKnowledgeBases(response.data.knowledgeBases);
      }
    } catch (error) {
      console.error('加载知识库失败:', error);
      toast.error('加载知识库失败');
    } finally {
      setLoading(false);
    }
  };

  // 获取默认知识库（第一个活跃的知识库）
  const getDefaultKnowledgeBase = (): KnowledgeBase | null => {
    return knowledgeBases.find(kb => kb.status === 'active') || null;
  };

  return (
    <KnowledgeBaseContext.Provider
      value={{
        knowledgeBases,
        loading,
        getDefaultKnowledgeBase,
        loadKnowledgeBases
      }}
    >
      {children}
    </KnowledgeBaseContext.Provider>
  );
}

export function useKnowledgeBase() {
  const context = useContext(KnowledgeBaseContext);
  if (context === undefined) {
    throw new Error('useKnowledgeBase must be used within a KnowledgeBaseContextProvider');
  }
  return context;
}