/**
 * 向量化相关类型定义
 * 用于知识库文档向量化进度显示功能
 */

/**
 * 向量化状态类型
 * - pending: 待向量化
 * - processing: 处理中
 * - completed: 已完成
 * - failed: 失败
 */
export type VectorStatus = 'pending' | 'processing' | 'completed' | 'failed';

/**
 * 向量化错误信息
 */
export interface VectorizationError {
  /** 文档ID */
  documentId: string;
  /** 文档标题 */
  title: string;
  /** 错误信息 */
  error: string;
}

/**
 * 向量化进度信息
 */
export interface VectorizationProgress {
  /** 
   * 任务状态
   * - idle: 空闲
   * - processing: 处理中
   * - completed: 已完成
   * - cancelled: 已取消
   * - error: 错误
   */
  status: 'idle' | 'processing' | 'completed' | 'cancelled' | 'error';
  /** 总文档数 */
  total: number;
  /** 已处理文档数 */
  processed: number;
  /** 成功处理的文档数 */
  successful: number;
  /** 失败的文档数 */
  failed: number;
  /** 当前正在处理的文档标题 */
  currentDocument: string | null;
  /** 错误列表 */
  errors: VectorizationError[];
  /** 任务开始时间（时间戳） */
  startTime: number | null;
  /** 任务结束时间（时间戳） */
  endTime: number | null;
}

/**
 * 文档向量化信息
 */
export interface DocumentVectorInfo {
  /** 向量化状态 */
  status: VectorStatus;
  /** 向量块数量 */
  chunkCount: number;
  /** 错误信息（如果失败） */
  error?: string;
}

/**
 * 向量化API请求选项
 */
export interface VectorizationOptions {
  /** 是否强制重新向量化 */
  force?: boolean;
  /** 文本块大小 */
  chunkSize?: number;
  /** 文本块重叠大小 */
  chunkOverlap?: number;
}

/**
 * 批量向量化请求选项
 */
export interface BatchVectorizationOptions extends VectorizationOptions {
  /** 要向量化的文档ID列表 */
  documentIds?: string[];
}

/**
 * 单文档向量化响应
 */
export interface VectorizeDocumentResponse {
  /** 成功标志 */
  success: boolean;
  /** 响应数据 */
  data: {
    /** 消息 */
    message: string;
    /** 文档信息 */
    document: {
      /** 文档ID */
      id: string;
      /** 文档标题 */
      title: string;
      /** 向量化状态 */
      vectorStatus: VectorStatus;
      /** 向量块数量 */
      chunkCount: number;
      /** 向量化错误信息 */
      vectorError: string | null;
    };
  };
}

/**
 * 批量向量化响应
 */
export interface SyncVectorsResponse {
  /** 成功标志 */
  success: boolean;
  /** 响应数据 */
  data: {
    /** 消息 */
    message: string;
    /** 统计摘要 */
    summary: {
      /** 总文档数 */
      total: number;
      /** 成功数 */
      success: number;
      /** 失败数 */
      failed: number;
      /** 跳过数 */
      skipped: number;
    };
    /** 错误列表 */
    errors?: VectorizationError[];
    /** 任务耗时（秒） */
    duration?: number;
  };
}
