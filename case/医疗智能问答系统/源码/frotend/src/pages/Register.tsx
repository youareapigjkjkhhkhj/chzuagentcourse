import { useState, useContext } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { AuthContext, UserRole } from '../contexts/authContext';
import { Input, Button, Form, Select } from 'tdesign-react';
import { toast } from 'sonner';
import { UserIcon, LockOnIcon, MailIcon } from 'tdesign-icons-react';

export default function Register() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [role, setRole] = useState<UserRole>('doctor');
  const [loading, setLoading] = useState(false);
  const { register: registerUser } = useContext(AuthContext);
  const navigate = useNavigate();

  const validateForm = () => {
    if (!name || !email || !password || !confirmPassword) {
      toast.error('请填写所有必填字段');
      return false;
    }

    if (password.length < 6) {
      toast.error('密码长度至少为6位');
      return false;
    }

    if (password !== confirmPassword) {
      toast.error('两次输入的密码不一致');
      return false;
    }

    // 简单的邮箱格式验证
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      toast.error('请输入有效的邮箱地址');
      return false;
    }

    return true;
  };

  const handleRegister = async (context: { e?: React.FormEvent; validateResult?: boolean; firstError?: boolean }) => {
    context.e?.preventDefault();
    
    if (!validateForm()) {
      return;
    }

    setLoading(true);

    try {
      // 使用AuthContext的register方法进行注册
      const success = await registerUser({
        name,
        email,
        password,
        role,
        username: name.replace(/\s+/g, '').toLowerCase() // 使用姓名作为用户名，去除空格并转为小写
      });
      
      if (success) {
        toast.success('注册成功！');
        navigate('/dashboard');
      } else {
        toast.error('注册失败，请重试');
      }
    } catch (error: any) {
      console.error('注册失败:', error);
      const errorMessage = error.response?.data?.message || '注册失败，请重试';
      toast.error(errorMessage);
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
            <h1 style={{ fontSize: 28, fontWeight: 'bold', color: '#3b82f6', margin: 0 }}>创建账号</h1>
            <p style={{ color: '#666', marginTop: 8 }}>请填写以下信息完成注册</p>
          </div>
          
          <Form onSubmit={handleRegister} labelWidth={0}>
            <Form.FormItem name="name">
              <Input
                value={name}
                onChange={(val) => setName(val as string)}
                placeholder="请输入您的姓名"
                prefixIcon={<UserIcon />}
                size="large"
              />
            </Form.FormItem>
            
            <Form.FormItem name="email">
              <Input
                type="email"
                value={email}
                onChange={(val) => setEmail(val as string)}
                placeholder="请输入邮箱"
                prefixIcon={<MailIcon />}
                size="large"
              />
            </Form.FormItem>
            
            <Form.FormItem name="role">
              <Select
                value={role}
                onChange={(val) => setRole(val as UserRole)}
                options={[
                  { label: '医生', value: 'doctor' },
                  { label: '管理员', value: 'admin' }
                ]}
                size="large"
              />
            </Form.FormItem>
            
            <Form.FormItem name="password">
              <Input
                type="password"
                value={password}
                onChange={(val) => setPassword(val as string)}
                placeholder="至少6位字符"
                prefixIcon={<LockOnIcon />}
                size="large"
              />
            </Form.FormItem>
            
            <Form.FormItem name="confirmPassword">
              <Input
                type="password"
                value={confirmPassword}
                onChange={(val) => setConfirmPassword(val as string)}
                placeholder="再次输入密码"
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
                注册
              </Button>
            </Form.FormItem>
          </Form>
          
          <div style={{ marginTop: 24, textAlign: 'center' }}>
            <p style={{ color: '#666', fontSize: 14 }}>
              已有账号？{' '}
              <Link to="/login" style={{ color: '#3b82f6', fontWeight: 500 }}>
                立即登录
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}