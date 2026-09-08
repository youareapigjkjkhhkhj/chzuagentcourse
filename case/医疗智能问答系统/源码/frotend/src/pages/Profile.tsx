import { useState, useEffect, useContext } from 'react';
import { useNavigate } from 'react-router-dom';
import { AuthContext } from '../contexts/authContext';
import { authAPI } from '../services/api';
import Navbar from '../components/Navbar';
import Sidebar from '../components/Sidebar';
import { Card, Form, Input, Button, Tabs, MessagePlugin } from 'tdesign-react';
import { SaveIcon, KeyIcon } from 'tdesign-icons-react';

export default function Profile() {
  const { user, updateUser } = useContext(AuthContext);
  const navigate = useNavigate();
  const [isLoading, setIsLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'profile' | 'password'>('profile');
  
  // 个人信息表单状态
  const [profileForm, setProfileForm] = useState({
    name: '',
    email: '',
    username: ''
  });
  
  // 修改密码表单状态
  const [passwordForm, setPasswordForm] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: ''
  });

  useEffect(() => {
    if (user) {
      setProfileForm({
        name: user.name || '',
        email: user.email || '',
        username: user.username || ''
      });
    }
  }, [user]);

  const handleProfileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setProfileForm(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handlePasswordChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setPasswordForm(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleUpdateProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    
    try {
      // 验证表单
      if (!profileForm.name.trim() || !profileForm.email.trim() || !profileForm.username.trim()) {
        toast.error('所有字段都是必填的');
        setIsLoading(false);
        return;
      }
      
      // 验证邮箱格式
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!emailRegex.test(profileForm.email)) {
        toast.error('请输入有效的邮箱地址');
        setIsLoading(false);
        return;
      }
      
      // 调用API更新个人信息
      const response = await authAPI.updateProfile({
        name: profileForm.name,
        email: profileForm.email,
        username: profileForm.username
      });
      
      if (response.data.success) {
        // 更新上下文中的用户信息
        updateUser(response.data.user);
        toast.success('个人信息已更新');
      } else {
        toast.error(response.data.message || '更新失败');
      }
    } catch (error: any) {
      console.error('更新个人信息失败:', error);
      toast.error(error.response?.data?.message || '更新个人信息失败');
    } finally {
      setIsLoading(false);
    }
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    
    try {
      // 验证表单
      if (!passwordForm.currentPassword || !passwordForm.newPassword || !passwordForm.confirmPassword) {
        toast.error('所有字段都是必填的');
        setIsLoading(false);
        return;
      }
      
      if (passwordForm.newPassword.length < 6) {
        toast.error('新密码长度至少为6位');
        setIsLoading(false);
        return;
      }
      
      if (passwordForm.newPassword !== passwordForm.confirmPassword) {
        toast.error('新密码和确认密码不匹配');
        setIsLoading(false);
        return;
      }
      
      // 调用API修改密码
      const response = await authAPI.changePassword({
        currentPassword: passwordForm.currentPassword,
        newPassword: passwordForm.newPassword
      });
      
      if (response.data.success) {
        toast.success('密码修改成功');
        // 清空表单
        setPasswordForm({
          currentPassword: '',
          newPassword: '',
          confirmPassword: ''
        });
      } else {
        toast.error(response.data.message || '修改密码失败');
      }
    } catch (error: any) {
      console.error('修改密码失败:', error);
      toast.error(error.response?.data?.message || '修改密码失败');
    } finally {
      setIsLoading(false);
    }
  };

  if (!user) {
    return null;
  }

  return (
    <div style={{ minHeight: '100vh', background: '#f5f5f5' }}>
      <Navbar />
      <div style={{ display: 'flex' }}>
        <Sidebar />
        <main style={{ flex: 1, marginLeft: 256, padding: 24 }}>
          <div style={{ maxWidth: 800, margin: '0 auto' }}>
            <header style={{ marginBottom: 32 }}>
              <h1 style={{ fontSize: 24, fontWeight: 'bold', color: '#333', margin: 0 }}>个人信息</h1>
              <p style={{ color: '#666', marginTop: 4 }}>查看和编辑您的个人资料信息</p>
            </header>
            
            <Tabs value={activeTab} onChange={(val) => setActiveTab(val as 'profile' | 'password')}>
              <Tabs.TabPanel value="profile" label="个人信息">
                <Card>
                  <div style={{ display: 'flex', alignItems: 'center', marginBottom: 24 }}>
                    <div style={{ 
                      width: 80, 
                      height: 80, 
                      background: '#e6f7ff', 
                      borderRadius: '50%', 
                      display: 'flex', 
                      alignItems: 'center', 
                      justifyContent: 'center',
                      marginRight: 16
                    }}>
                      <span style={{ color: '#3b82f6', fontSize: 32, fontWeight: 500 }}>{user.name.charAt(0)}</span>
                    </div>
                    <div>
                      <h3 style={{ fontSize: 18, fontWeight: 600, color: '#333', margin: 0 }}>{user.name}</h3>
                      <p style={{ fontSize: 14, color: '#999', marginTop: 4 }}>角色: {user.role === 'admin' ? '管理员' : '医生'}</p>
                    </div>
                  </div>
                  
                  <Form onSubmit={handleUpdateProfile} labelWidth={80}>
                    <Form.FormItem label="姓名" name="name" rules={[{ required: true }]}>
                      <Input
                        value={profileForm.name}
                        onChange={(val) => setProfileForm(prev => ({ ...prev, name: val as string }))}
                      />
                    </Form.FormItem>
                    
                    <Form.FormItem label="用户名" name="username" rules={[{ required: true }]}>
                      <Input
                        value={profileForm.username}
                        onChange={(val) => setProfileForm(prev => ({ ...prev, username: val as string }))}
                      />
                    </Form.FormItem>
                    
                    <Form.FormItem label="邮箱" name="email" rules={[{ required: true }, { pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/, message: '请输入有效的邮箱地址' }]}>
                      <Input
                        type="email"
                        value={profileForm.email}
                        onChange={(val) => setProfileForm(prev => ({ ...prev, email: val as string }))}
                      />
                    </Form.FormItem>
                    
                    <Form.FormItem label="角色">
                      <Input value={user.role === 'admin' ? '管理员' : '医生'} disabled />
                    </Form.FormItem>
                    
                    <Form.FormItem>
                      <Button theme="primary" type="submit" loading={isLoading} icon={<SaveIcon />}>
                        保存更改
                      </Button>
                    </Form.FormItem>
                  </Form>
                </Card>
              </Tabs.TabPanel>
              
              <Tabs.TabPanel value="password" label="修改密码">
                <Card>
                  <div style={{ marginBottom: 24 }}>
                    <h3 style={{ fontSize: 18, fontWeight: 600, color: '#333', margin: 0 }}>修改密码</h3>
                    <p style={{ fontSize: 14, color: '#999', marginTop: 8 }}>
                      为了您的账户安全，请定期更换密码并使用强密码。
                    </p>
                  </div>
                  
                  <Form onSubmit={handleChangePassword} labelWidth={100}>
                    <Form.FormItem label="当前密码" name="currentPassword" rules={[{ required: true }]}>
                      <Input type="password" />
                    </Form.FormItem>
                    
                    <Form.FormItem label="新密码" name="newPassword" rules={[{ required: true }, { min: 6, message: '密码长度至少为6位' }]}>
                      <Input type="password" />
                    </Form.FormItem>
                    
                    <Form.FormItem label="确认新密码" name="confirmPassword" rules={[{ required: true }, { validator: (val) => val === passwordForm.newPassword ? true : '密码不匹配' }]}>
                      <Input type="password" />
                    </Form.FormItem>
                    
                    <Form.FormItem>
                      <Button theme="primary" type="submit" loading={isLoading} icon={<KeyIcon />}>
                        修改密码
                      </Button>
                    </Form.FormItem>
                  </Form>
                </Card>
              </Tabs.TabPanel>
            </Tabs>
          </div>
        </main>
      </div>
    </div>
  );
}