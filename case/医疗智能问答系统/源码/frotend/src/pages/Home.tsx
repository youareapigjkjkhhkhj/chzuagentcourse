import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useContext } from 'react';
import { AuthContext } from '../contexts/authContext';
import { Button } from 'tdesign-react';

export default function Home() {
  const navigate = useNavigate();
  const { isAuthenticated } = useContext(AuthContext);

  // 检查用户是否已登录
  useEffect(() => {
    if (isAuthenticated) {
      navigate('/dashboard');
    } else {
      // 检查localStorage中是否有保存的用户信息
      const savedUser = localStorage.getItem('authUser');
      if (savedUser) {
        navigate('/dashboard');
      } else {
        // 自动跳转到登录页
        navigate('/login');
      }
    }
  }, [isAuthenticated, navigate]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', background: '#fff' }}>
      <div style={{ textAlign: 'center' }}>
        <h1 style={{ fontSize: 40, fontWeight: 'bold', color: '#3b82f6', marginBottom: 16 }}>AI糖尿病辅助诊断系统</h1>
        <p style={{ fontSize: 20, color: '#666', marginBottom: 32 }}>基于人工智能的糖尿病视网膜病变筛查解决方案</p>
        <div style={{ display: 'flex', justifyContent: 'center', gap: 16 }}>
          <Button theme="primary" size="large" onClick={() => navigate('/login')}>
            登录系统
          </Button>
        </div>
      </div>
    </div>
  );
}