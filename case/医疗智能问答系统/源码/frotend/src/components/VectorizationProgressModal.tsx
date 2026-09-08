import React, { useEffect, useState, useCallback } from 'react';
import { Dialog, Button, Progress, Loading, Checkbox, MessagePlugin } from 'tdesign-react';
import { CheckCircleIcon, ErrorCircleIcon, CloseIcon, RefreshIcon } from 'tdesign-icons-react';
import { VectorizationProgress } from '../types/vectorization';

interface VectorizationProgressModalProps {
  /** 是否打开对话框 */
  isOpen: boolean;
  /** 关闭对话框回调 */
  onClose: () => void;
  /** 向量化进度数据 */
  progress: VectorizationProgress;
  /** 取消向量化回调 */
  onCancel?: () => void;
  /** 重试失败文档回调 */
  onRetry?: (documentIds: string[]) => void;
}

/**
 * 向量化进度对话框组件
 * 显示文档向量化的实时进度、统计信息和结果摘要
 */
const VectorizationProgressModal: React.FC<VectorizationProgressModalProps> = ({
  isOpen,
  onClose,
  progress,
  onCancel,
  onRetry
}) => {
  const [duration, setDuration] = useState<number>(0);
  const [showCancelConfirm, setShowCancelConfirm] = useState<boolean>(false);
  const [selectedRetryDocs, setSelectedRetryDocs] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  // 计算任务耗时
  useEffect(() => {
    if (progress.status === 'processing' && progress.startTime) {
      const interval = setInterval(() => {
        setDuration((Date.now() - progress.startTime!) / 1000);
      }, 100);
      return () => clearInterval(interval);
    } else if (progress.endTime && progress.startTime) {
      setDuration((progress.endTime - progress.startTime) / 1000);
    }
  }, [progress.status, progress.startTime, progress.endTime]);

  // 模拟加载状态，用于骨架屏
  useEffect(() => {
    if (isOpen) {
      setIsLoading(true);
      const timer = setTimeout(() => setIsLoading(false), 300);
      return () => clearTimeout(timer);
    }
  }, [isOpen]);

  // 键盘快捷键支持 - ESC 关闭对话框
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isOpen) {
        if (showCancelConfirm) {
          // 如果取消确认对话框打开，先关闭它
          handleCancelConfirmClose();
        } else if (progress.status !== 'processing') {
          // 只有在非处理状态下才允许 ESC 关闭
          handleClose();
        }
      }
    };

    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      return () => document.removeEventListener('keydown', handleKeyDown);
    }
  }, [isOpen, progress.status, showCancelConfirm]);

  // 计算完成百分比
  const percentage = progress.total > 0 
    ? Math.round((progress.processed / progress.total) * 100) 
    : 0;

  // 格式化耗时
  const formatDuration = (seconds: number): string => {
    if (seconds < 60) {
      return `${seconds.toFixed(1)} 秒`;
    }
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.floor(seconds % 60);
    return `${minutes} 分 ${remainingSeconds} 秒`;
  };

  // 处理关闭
  const handleClose = useCallback(() => {
    // 只有在完成、取消或错误状态下才允许关闭
    if (progress.status !== 'processing') {
      onClose();
    }
  }, [progress.status, onClose]);

  // 处理取消按钮点击
  const handleCancelClick = () => {
    if (progress.status === 'processing') {
      setShowCancelConfirm(true);
    }
  };

  // 确认取消
  const handleConfirmCancel = () => {
    if (onCancel) {
      onCancel();
    }
    setShowCancelConfirm(false);
  };

  // 取消确认对话框
  const handleCancelConfirmClose = useCallback(() => {
    setShowCancelConfirm(false);
  }, []);

  // 处理重试失败文档
  const handleRetryFailed = () => {
    if (onRetry && progress.errors.length > 0) {
      const failedDocIds = progress.errors.map(err => err.documentId);
      onRetry(failedDocIds);
    }
  };

  // 处理重试选中的文档
  const handleRetrySelected = () => {
    if (onRetry && selectedRetryDocs.length > 0) {
      onRetry(selectedRetryDocs);
      setSelectedRetryDocs([]);
    }
  };

  // 切换选中重试文档
  const toggleRetryDoc = (docId: string) => {
    setSelectedRetryDocs(prev => 
      prev.includes(docId) 
        ? prev.filter(id => id !== docId)
        : [...prev, docId]
    );
  };

  // 全选/取消全选失败文档
  const toggleSelectAllFailed = () => {
    if (selectedRetryDocs.length === progress.errors.length) {
      setSelectedRetryDocs([]);
    } else {
      setSelectedRetryDocs(progress.errors.map(err => err.documentId));
    }
  };

  // 获取友好的错误消息
  const getFriendlyErrorMessage = (error: string): string => {
    if (error.includes('network') || error.includes('fetch') || error.includes('连接')) {
      return '网络连接失败，请检查网络后重试';
    }
    if (error.includes('timeout') || error.includes('超时')) {
      return '请求超时，请稍后重试';
    }
    if (error.includes('embedding') || error.includes('嵌入')) {
      return '嵌入模型处理失败，请检查模型配置';
    }
    if (error.includes('401') || error.includes('403') || error.includes('unauthorized')) {
      return '认证失败，请重新登录';
    }
    if (error.includes('500') || error.includes('服务器')) {
      return '服务器错误，请稍后重试';
    }
    return error || '未知错误';
  };

  // 获取状态图标和颜色
  const getStatusIcon = (status: VectorizationProgress['status']) => {
    switch (status) {
      case 'processing':
        return { icon: 'fa-spinner fa-spin', color: 'text-blue-500' };
      case 'completed':
        return { icon: 'fa-check-circle', color: 'text-green-500' };
      case 'cancelled':
        return { icon: 'fa-ban', color: 'text-yellow-500' };
      case 'error':
        return { icon: 'fa-exclamation-circle', color: 'text-red-500' };
      default:
        return { icon: 'fa-circle', color: 'text-gray-400' };
    }
  };

  const statusIcon = getStatusIcon(progress.status);

  // 对话框动画变体
  const modalVariants = {
    hidden: { 
      opacity: 0, 
      scale: 0.9, 
      y: -20 
    },
    visible: { 
      opacity: 1, 
      scale: 1, 
      y: 0,
      transition: {
        type: "spring",
        stiffness: 300,
        damping: 30
      }
    },
    exit: { 
      opacity: 0, 
      scale: 0.95, 
      y: -20,
      transition: {
        duration: 0.2
      }
    }
  };

  // 渲染加载骨架屏
  const renderSkeleton = () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{ height: 16, background: '#f0f0f0', borderRadius: 4, width: 80, margin: '0 auto 8px' }}></div>
        <div style={{ height: 20, background: '#f0f0f0', borderRadius: 4, width: 192, margin: '0 auto' }}></div>
      </div>
      <div>
        <Progress percentage={0} />
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
          <div style={{ height: 16, background: '#f0f0f0', borderRadius: 4, width: 48 }}></div>
          <div style={{ height: 16, background: '#f0f0f0', borderRadius: 4, width: 64 }}></div>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, textAlign: 'center' }}>
        {[1, 2, 3].map((i) => (
          <div key={i}>
            <div style={{ height: 32, background: '#f0f0f0', borderRadius: 4, width: 48, margin: '0 auto 8px' }}></div>
            <div style={{ height: 12, background: '#f0f0f0', borderRadius: 4, width: 64, margin: '0 auto' }}></div>
          </div>
        ))}
      </div>
      <div style={{ textAlign: 'center' }}>
        <div style={{ height: 40, background: '#f0f0f0', borderRadius: 8, width: 96, margin: '0 auto' }}></div>
      </div>
    </div>
  );

  // 渲染处理中的视图
  const renderProcessingView = () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {progress.currentDocument && (
        <div style={{ textAlign: 'center' }}>
          <p style={{ fontSize: 14, color: '#666', marginBottom: 4 }}>正在处理:</p>
          <p style={{ fontSize: 16, fontWeight: 500, color: '#333', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {progress.currentDocument}
          </p>
        </div>
      )}

      <div>
        <Progress percentage={percentage} status="active" />
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 14, color: '#666' }}>
          <span>{percentage}%</span>
          <span>{formatDuration(duration)}</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, textAlign: 'center' }}>
        <div>
          <div style={{ fontSize: 24, fontWeight: 'bold', color: '#333' }}>{progress.processed}</div>
          <div style={{ fontSize: 12, color: '#666' }}>已处理</div>
        </div>
        <div>
          <div style={{ fontSize: 24, fontWeight: 'bold', color: '#52c41a' }}>{progress.successful}</div>
          <div style={{ fontSize: 12, color: '#666' }}>成功</div>
        </div>
        <div>
          <div style={{ fontSize: 24, fontWeight: 'bold', color: '#f56c6c' }}>{progress.failed}</div>
          <div style={{ fontSize: 12, color: '#666' }}>失败</div>
        </div>
      </div>

      <div style={{ textAlign: 'center' }}>
        <Button theme="default" onClick={handleCancelClick}>取消</Button>
      </div>

      <Dialog
        header="确认取消"
        visible={showCancelConfirm}
        onClose={handleCancelConfirmClose}
        footer={
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Button theme="default" onClick={handleCancelConfirmClose}>继续处理</Button>
            <Button theme="danger" onClick={handleConfirmCancel}>确认取消</Button>
          </div>
        }
      >
        <p>确定要取消向量化任务吗？已完成的文档将被保留，但未处理的文档将被跳过。</p>
      </Dialog>
    </div>
  );

  // 渲染完成摘要视图
  const renderSummaryView = () => {
    const isSuccess = progress.status === 'completed';
    const isCancelled = progress.status === 'cancelled';
    const isError = progress.status === 'error';

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 64,
            height: 64,
            borderRadius: '50%',
            backgroundColor: isSuccess ? '#f6ffed' : isCancelled ? '#fffbe6' : '#fff2f0',
            marginBottom: 12
          }}>
            {isSuccess && <CheckCircleIcon style={{ fontSize: 32, color: '#52c41a' }} />}
            {isCancelled && <CloseIcon style={{ fontSize: 32, color: '#faad14' }} />}
            {isError && <ErrorCircleIcon style={{ fontSize: 32, color: '#f5222d' }} />}
          </div>
          <h3 style={{ fontSize: 18, fontWeight: 600, color: '#333', margin: 0 }}>
            {isSuccess && progress.failed === 0 && '向量化完成！'}
            {isSuccess && progress.failed > 0 && '向量化部分完成'}
            {isCancelled && '向量化已取消'}
            {isError && '向量化失败'}
          </h3>
          {isSuccess && progress.failed === 0 && (
            <p style={{ fontSize: 14, color: '#666', marginTop: 4 }}>所有文档已成功向量化</p>
          )}
        </div>

        <div style={{ background: '#f5f5f5', borderRadius: 8, padding: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 14, color: '#666' }}>总计:</span>
            <span style={{ fontSize: 14, fontWeight: 500, color: '#333' }}>{progress.total} 个文档</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 14, color: '#666' }}>成功:</span>
            <span style={{ fontSize: 14, fontWeight: 500, color: '#52c41a' }}>{progress.successful} 个</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 14, color: '#666' }}>失败:</span>
            <span style={{ fontSize: 14, fontWeight: 500, color: '#f5222d' }}>{progress.failed} 个</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 14, color: '#666' }}>耗时:</span>
            <span style={{ fontSize: 14, fontWeight: 500, color: '#333' }}>{formatDuration(duration)}</span>
          </div>
        </div>

        {progress.errors.length > 0 && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <h4 style={{ fontSize: 14, fontWeight: 500, color: '#333', margin: 0 }}>失败文档:</h4>
              {onRetry && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Button size="small" theme="default" onClick={toggleSelectAllFailed}>
                    {selectedRetryDocs.length === progress.errors.length ? '取消全选' : '全选'}
                  </Button>
                  {selectedRetryDocs.length > 0 && (
                    <Button size="small" theme="primary" onClick={handleRetrySelected}>
                      重试选中 ({selectedRetryDocs.length})
                    </Button>
                  )}
                </div>
              )}
            </div>
            <div style={{ maxHeight: 192, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
              {progress.errors.map((error, index) => (
                <div key={index} style={{ background: '#fff2f0', border: '1px solid #ffccc7', borderRadius: 8, padding: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start' }}>
                    {onRetry && (
                      <Checkbox
                        checked={selectedRetryDocs.includes(error.documentId)}
                        onChange={() => toggleRetryDoc(error.documentId)}
                        style={{ marginRight: 8, marginTop: 2 }}
                      />
                    )}
                    <ErrorCircleIcon style={{ color: '#f5222d', marginRight: 8, marginTop: 2, flexShrink: 0 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{ fontSize: 14, fontWeight: 500, color: '#333', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {error.title}
                      </p>
                      <p style={{ fontSize: 12, color: '#f5222d', marginTop: 4 }}>
                        {getFriendlyErrorMessage(error.error)}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            {onRetry && (
              <Button
                theme="warning"
                icon={<RefreshIcon />}
                onClick={handleRetryFailed}
                style={{ width: '100%', marginTop: 8 }}
              >
                重试所有失败文档
              </Button>
            )}
          </div>
        )}

        <div style={{ textAlign: 'center' }}>
          <Button theme="primary" onClick={handleClose}>关闭</Button>
        </div>
      </div>
    );
  };

  return (
    <Dialog
      header={
        <div style={{ display: 'flex', alignItems: 'center' }}>
          {progress.status === 'processing' ? (
            <Loading size="small" style={{ marginRight: 8 }} />
          ) : (
            statusIcon.icon
          )}
          {progress.status === 'processing' ? '向量化进度' : '向量化结果'}
        </div>
      }
      visible={isOpen}
      onClose={progress.status !== 'processing' ? handleClose : undefined}
      footer={null}
      width={480}
    >
      <div style={{ padding: 16 }}>
        {isLoading ? renderSkeleton() : (
          progress.status === 'processing' ? renderProcessingView() : renderSummaryView()
        )}
      </div>
    </Dialog>
  );
};

export default VectorizationProgressModal;
