import { Empty as TDEmpty } from 'tdesign-react';

// Empty component
export function Empty() {
  return (
    <TDEmpty 
      description="暂无数据"
      style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
    />
  );
}