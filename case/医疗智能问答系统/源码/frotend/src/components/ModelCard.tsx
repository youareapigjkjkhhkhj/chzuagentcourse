import { AIModel } from '../types';
import { getModelFeatures } from '../types';
import { Card, Tag, Progress, Space } from 'tdesign-react';

interface ModelCardProps {
  model: AIModel;
  accuracy: number;
  precision: number;
  recall: number;
  f1Score: number;
  isActive?: boolean;
  onClick?: (model: AIModel) => void;
}

export default function ModelCard({
  model,
  accuracy,
  precision,
  recall,
  f1Score,
  isActive = false,
  onClick
}: ModelCardProps) {
  
  // 模型图标映射
  const modelIcons: Record<AIModel, string> = {
    'ResNet': 'fa-network-wired',
    'DenseNet': 'fa-project-diagram',
    'EfficientNet': 'fa-bolt'
  };
  
  // 模型颜色映射
  const modelColors: Record<AIModel, string> = {
    'ResNet': 'border-blue-500 bg-blue-50',
    'DenseNet': 'border-green-500 bg-green-50',
    'EfficientNet': 'border-purple-500 bg-purple-50'
  };
  
  const handleClick = () => {
    if (onClick) {
      onClick(model);
    }
  };
  
  return (
    <Card
      hover
      onClick={handleClick}
      style={{
        cursor: 'pointer',
        border: isActive ? '2px solid #3b82f6' : '1px solid #e5e5e5',
        borderColor: isActive ? '#3b82f6' : '#e5e5e5'
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <div style={{
            width: 40,
            height: 40,
            borderRadius: '50%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginRight: 12,
            backgroundColor: model === 'ResNet' ? '#e6f7ff' : model === 'DenseNet' ? '#f6ffed' : '#f9f0ff',
            color: model === 'ResNet' ? '#1890ff' : model === 'DenseNet' ? '#52c41a' : '#722ed1'
          }}>
            {model === 'ResNet' ? 'R' : model === 'DenseNet' ? 'D' : 'E'}
          </div>
          <div>
            <h3 style={{ fontWeight: 600, color: '#333', margin: 0 }}>{model}</h3>
            <p style={{ fontSize: 12, color: '#999', margin: 0 }}>{getModelFeatures(model)}</p>
          </div>
        </div>
        {isActive && (
          <Tag theme="primary">已选择</Tag>
        )}
      </div>
      
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
            <span style={{ color: '#666' }}>准确率</span>
            <span style={{ fontWeight: 500 }}>{(accuracy * 100).toFixed(1)}%</span>
          </div>
          <Progress percentage={accuracy * 100} status="success" />
        </div>
        
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
            <span style={{ color: '#666' }}>精确率</span>
            <span style={{ fontWeight: 500 }}>{(precision * 100).toFixed(1)}%</span>
          </div>
          <Progress percentage={precision * 100} status="success" />
        </div>
        
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
            <span style={{ color: '#666' }}>召回率</span>
            <span style={{ fontWeight: 500 }}>{(recall * 100).toFixed(1)}%</span>
          </div>
          <Progress percentage={recall * 100} status="warning" />
        </div>
        
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
            <span style={{ color: '#666' }}>F1分数</span>
            <span style={{ fontWeight: 500 }}>{(f1Score * 100).toFixed(1)}%</span>
          </div>
          <Progress percentage={f1Score * 100} status="warning" />
        </div>
      </div>
    </Card>
  );
}