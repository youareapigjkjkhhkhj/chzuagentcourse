import { useContext } from 'react';
import { NavLink } from 'react-router-dom';
import { AuthContext } from '../contexts/authContext';
import { motion } from 'framer-motion';
import { Menu } from 'tdesign-react';
import { 
  DashboardIcon, 
  ImageIcon, 
  FileIcon, 
  RobotIcon, 
  ChatIcon, 
  BookIcon, 
  ServerIcon, 
  UsergroupIcon, 
  SettingIcon 
} from 'tdesign-icons-react';

export default function Sidebar() {
  const { user } = useContext(AuthContext);
  
  if (!user) {
    return null;
  }

  const isAdmin = user.role === 'admin';

  // 导航项目配置
  const navItems = [
    {
      path: '/dashboard',
      icon: <DashboardIcon />,
      label: '仪表盘',
      accessibleTo: ['doctor', 'admin']
    },
    {
      path: '/analysis',
      icon: <ImageIcon />,
      label: '图像分析',
      accessibleTo: ['doctor', 'admin']
    },
    {
      path: '/reports',
      icon: <FileIcon />,
      label: '诊断报告',
      accessibleTo: ['doctor', 'admin']
    },
    {
      path: '/ai-assistant',
      icon: <RobotIcon />,
      label: 'AI医学助手',
      accessibleTo: ['doctor', 'admin']
    },
    {
      path: '/chat-history',
      icon: <ChatIcon />,
      label: '聊天记录',
      accessibleTo: ['doctor', 'admin']
    },
    {
      path: '/knowledge',
      icon: <BookIcon />,
      label: '医学知识库',
      accessibleTo: ['doctor', 'admin']
    },
    {
      path: '/knowledge-settings',
      icon: <ServerIcon />,
      label: '知识库设置',
      accessibleTo: ['admin']
    },
    {
      path: '/models',
      icon: <RobotIcon />,
      label: '模型管理',
      accessibleTo: ['admin']
    },
    {
      path: '/users',
      icon: <UsergroupIcon />,
      label: '用户管理',
      accessibleTo: ['admin']
    },
    {
      path: '/settings',
      icon: <SettingIcon />,
      label: '系统设置',
      accessibleTo: ['admin']
    }
  ];

  // 根据用户角色过滤可访问的导航项目
  const accessibleItems = navItems.filter(item => 
    item.accessibleTo.includes(user.role)
  );

  return (
    <div className="w-64 bg-white border-r border-gray-200 h-[calc(100vh-4rem)] fixed overflow-y-auto">
      <div className="p-4">
        <div className="mb-8">
          <div className="text-sm font-medium text-gray-500 uppercase tracking-wider">
            主菜单
          </div>
          <Menu theme="light" style={{ marginTop: '16px' }}>
            {accessibleItems.map((item, index) => (
              <Menu.MenuItem key={item.path} value={item.path} icon={item.icon}>
                <NavLink
                  to={item.path}
                  className={({ isActive }) =>
                    `block w-full ${
                      isActive
                        ? 'text-blue-700'
                        : 'text-gray-700'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              </Menu.MenuItem>
            ))}
          </Menu>
        </div>
        
        <div>
          <div className="text-sm font-medium text-gray-500 uppercase tracking-wider">
            账户
          </div>
          <div className="mt-4 bg-blue-50 rounded-lg p-3">
            <div className="flex items-center">
              <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center mr-3">
                <span className="text-blue-600 font-medium">{user.name.charAt(0)}</span>
              </div>
              <div>
                <div className="text-sm font-medium text-gray-900">{user.name}</div>
                <div className="text-xs text-gray-500">{user.role === 'admin' ? '管理员' : '医生'}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}