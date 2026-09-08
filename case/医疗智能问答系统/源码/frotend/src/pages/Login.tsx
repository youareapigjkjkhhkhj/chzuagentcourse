import { useState, useContext } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { AuthContext } from '../contexts/authContext';
import { Input, Button, Form, MessagePlugin } from 'tdesign-react';
import { UserIcon, LockOnIcon } from 'tdesign-icons-react';
import { toast } from 'sonner';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useContext(AuthContext);
  const navigate = useNavigate();

  const handleLogin = async (context: { e?: React.FormEvent; validateResult?: boolean; firstError?: boolean }) => {
    context.e?.preventDefault();
    
    if (!email || !password) {
      toast.error('请输入邮箱和密码');
      return;
    }

    setLoading(true);

    try {
      const success = await login(email, password);
      
      if (success) {
        toast.success('登录成功');
        navigate('/dashboard');
      } else {
        toast.error('邮箱或密码错误');
      }
    } catch (error) {
      console.error('Login error:', error);
      toast.error('登录失败，请检查网络连接');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: '#fff' }}>
      <div style={{ 
        display: 'none', 
        width: '50%', 
        background: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 40
      }} className="md:flex">
        <div style={{ textAlign: 'center', color: '#fff' }}>
          <h2 style={{ fontSize: 32, fontWeight: 'bold', marginBottom: 24 }}>AI糖尿病辅助诊断系统</h2>
          <p style={{ fontSize: 18, marginBottom: 32 }}>基于人工智能的糖尿病视网膜病变筛查解决方案</p>
          <img 
            src="src/asserts/images/logo.png"
            alt="AI医学诊断系统" 
            style={{ width: '100%', borderRadius: 8, boxShadow: '0 10px 25px rgba(0,0,0,0.2)' }}
          />
        </div>
      </div>
      
      <div style={{ 
        display: 'flex', 
        width: '100%', 
        alignItems: 'center', 
        justifyContent: 'center',
        padding: 32
      }}>
        <div style={{ width: '100%', maxWidth: 400 }}>
          <div style={{ textAlign: 'center', marginBottom: 32 }}>
            <h1 style={{ fontSize: 28, fontWeight: 'bold', color: '#3b82f6', margin: 0 }}>登录系统</h1>
            <p style={{ color: '#666', marginTop: 8 }}>请输入您的邮箱和密码</p>
          </div>
          
          <Form onSubmit={handleLogin} labelWidth={0}>
            <Form.FormItem name="email">
              <Input
                value={email}
                onChange={(val) => setEmail(val as string)}
                placeholder="请输入邮箱"
                prefixIcon={<UserIcon />}
                size="large"
              />
            </Form.FormItem>
            
            <Form.FormItem name="password">
              <Input
                type="password"
                value={password}
                onChange={(val) => setPassword(val as string)}
                placeholder="请输入密码"
                prefixIcon={<LockOnIcon />}
                size="large"
              />
            </Form.FormItem>
            
            <Form.FormItem>
              <Button
                theme="primary"
                type="submit"
                block
                size="large"
                loading={loading}
              >
                登录
              </Button>
            </Form.FormItem>
          </Form>
          
          <div style={{ marginTop: 24, textAlign: 'center' }}>
            <p style={{ color: '#666', fontSize: 14 }}>
              还没有账号？{' '}
              <Link to="/register" style={{ color: '#3b82f6', fontWeight: 500 }}>
                点击注册
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}