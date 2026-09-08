import { Tag, Tooltip, Loading } from 'tdesign-react';
import { CheckCircleIcon, ErrorCircleIcon, InfoCircleIcon } from 'tdesign-icons-react';
import { VectorStatus } from '../types/vectorization';

interface DocumentVectorStatusProps {
  /** 向量化状态 */
  status: VectorStatus;
  /** 向量块数量 */
  chunkCount?: number;
  /** 错误信息 */
  error?: string;
}

/**
 * 文档向量化状态指示器组件
 * 显示文档的向量化状态，包括图标、颜色和相关信息
 */
export default function DocumentVectorStatus({ 
  status, 
  chunkCount = 0, 
  error 
}: DocumentVectorStatusProps) {
  
  // 根据状态返回对应的配置
  const getStatusConfig = () => {
    switch (status) {
      case 'pending':
        return {
          icon: 'fa-circle',
          color: 'text-gray-400',
          bgColor: 'bg-gray-100',
          text: '待向量化',
          animate: false
        };
      case 'processing':
        return {
          icon: 'fa-spinner',
          color: 'text-blue-500',
          bgColor: 'bg-blue-50',
          text: '处理中',
          animate: true
        };
      case 'completed':
        return {
          icon: 'fa-check-circle',
          color: 'text-green-500',
          bgColor: 'bg-green-50',
          text: `已完成 (${chunkCount}块)`,
          animate: false
        };
      case 'failed':
        return {
          icon: 'fa-exclamation-circle',
          color: 'text-red-500',
          bgColor: 'bg-red-50',
          text: '失败',
          animate: false
        };
      default:
        return {
          icon: 'fa-circle',
          color: 'text-gray-400',
          bgColor: 'bg-gray-100',
          text: '未知',
          animate: false
        };
    }
  };

  const getStatusConfig = () => {
    switch (status) {
      case 'pending':
        return {
          theme: 'default',
          icon: <InfoCircleIcon />,
          text: '待向量化'
        };
      case 'processing':
        return {
          theme: 'primary',
          icon: <Loading size="small" />,
          text: '处理中'
        };
      case 'completed':
        return {
          theme: 'success',
          icon: <CheckCircleIcon />,
          text: `已完成 (${chunkCount}块)`
        };
      case 'failed':
        return {
          theme: 'danger',
          icon: <ErrorCircleIcon />,
          text: '失败'
        };
      default:
        return {
          theme: 'default',
          icon: <InfoCircleIcon />,
          text: '未知'
        };
    }
  };

  const config = getStatusConfig();

  return (
    <div style={{ display: 'inline-flex', alignItems: 'center' }}>
      <Tag theme={config.theme as any} icon={config.icon}>
        {config.text}
      </Tag>
      
      {status === 'failed' && error && (
        <Tooltip content={error}>
          <InfoCircleIcon style={{ marginLeft: 8, color: '#999', cursor: 'pointer' }} />
        </Tooltip>
      )}
    </div>
  );
}
