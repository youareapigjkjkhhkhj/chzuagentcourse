import { useContext, useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { AuthContext } from '../contexts/authContext';
import { toast } from 'sonner';
import { motion, AnimatePresence } from 'framer-motion';
import { useTheme } from '../hooks/useTheme';
import { Dropdown, Button, Avatar } from 'tdesign-react';
import { UserIcon, SettingIcon, LogoutIcon, SunnyIcon, MoonIcon } from 'tdesign-icons-react';

export default function Navbar() {
  const { isAuthenticated, user, logout } = useContext(AuthContext);
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  const handleLogout = () => {
    logout();
    toast.success('已成功登出');
    navigate('/login');
  };

  // 点击外部关闭下拉菜单
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (isDropdownOpen) {
        setIsDropdownOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isDropdownOpen]);

  if (!isAuthenticated || !user) {
    return null;
  }

  return (
    <nav className="bg-white border-b border-gray-200 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-16">
          <div className="flex">
            <div className="flex-shrink-0 flex items-center">
              <h1 className="text-xl font-bold text-blue-600">
                <i className="fas fa-heartbeat mr-2"></i>AI糖尿病辅助诊断系统
              </h1>
            </div>
          </div>
          
          <div className="flex items-center">
            {/* 主题切换按钮 */}
            <Button
              theme="default"
              variant="text"
              icon={theme === 'light' ? <MoonIcon /> : <SunnyIcon />}
              onClick={toggleTheme}
              aria-label="切换主题"
            />
            
            {/* 用户信息和下拉菜单 */}
            <div className="ml-4 relative">
              <Dropdown
                trigger="click"
                popupProps={{ visible: isDropdownOpen, onVisibleChange: setIsDropdownOpen }}
                menu={[
                  {
                    content: '个人信息',
                    prefixIcon: <UserIcon />,
                    onClick: () => {
                      navigate('/profile');
                      setIsDropdownOpen(false);
                    }
                  },
                  {
                    content: '设置',
                    prefixIcon: <SettingIcon />,
                    onClick: () => {
                      navigate('/settings');
                      setIsDropdownOpen(false);
                    }
                  },
                  {
                    content: '退出登录',
                    prefixIcon: <LogoutIcon />,
                    theme: 'danger',
                    onClick: handleLogout
                  }
                ]}
              >
                <div className="flex items-center cursor-pointer">
                  <Avatar size="small" style={{ marginRight: 8 }}>
                    {user.name.charAt(0)}
                  </Avatar>
                  <span className="text-sm font-medium text-gray-700">{user.name}</span>
                </div>
              </Dropdown>
            </div>
          </div>
        </div>
      </div>
    </nav>
  );
}