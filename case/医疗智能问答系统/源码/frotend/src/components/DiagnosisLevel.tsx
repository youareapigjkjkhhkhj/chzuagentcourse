import { DiagnosisLevel as DiagnosisLevelType } from '../types';
import { getDiagnosisColor, getDiagnosisName, getDiagnosisDescription } from '../types';
import { Tag } from 'tdesign-react';

interface DiagnosisLevelProps {
  level: DiagnosisLevelType;
  size?: 'small' | 'medium' | 'large';
  showDescription?: boolean;
}

export default function DiagnosisLevel({ 
  level, 
  size = 'medium', 
  showDescription = false 
}: DiagnosisLevelProps) {
  
  // 根据尺寸确定样式
  const sizeMap = {
    small: 'small',
    medium: 'medium',
    large: 'large'
  };
  
  return (
    <div>
      <Tag 
        theme="primary" 
        size={sizeMap[size]}
        style={{ backgroundColor: getDiagnosisColor(level) }}
      >
        {getDiagnosisName(level)}
      </Tag>
      
      {showDescription && (
        <div style={{ marginTop: 8, fontSize: 12, color: '#666', padding: 8, background: '#f5f5f5', borderRadius: 4 }}>
          {getDiagnosisDescription(level)}
        </div>
      )}
    </div>
  );
}