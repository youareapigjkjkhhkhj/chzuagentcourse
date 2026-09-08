import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { authAPI, transformUser } from '../services/api';

// 用户角色类型定义
export type UserRole = 'doctor' | 'admin';

// 用户信息接口
export interface UserInfo {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  lastLogin?: string;
}

// AuthContext接口定义
interface AuthContextType {
  isAuthenticated: boolean;
  user: UserInfo | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<boolean>;
  register: (userData: {
    username: string;
    email: string;
    password: string;
    name: string;
    role: UserRole;
  }) => Promise<boolean>;
  logout: () => void;
  setUser: (user: UserInfo | null) => void;
  updateUser: (updatedUser: Partial<UserInfo>) => void;
}

// 创建AuthContext
export const AuthContext = createContext<AuthContextType>({
  isAuthenticated: false,
  user: null,
  loading: true,
  login: async () => false,
  register: async () => false,
  logout: () => {},
  setUser: () => {},
  updateUser: () => {},
});

// AuthProvider组件
interface AuthProviderProps {
  children: ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [loading, setLoading] = useState(true);

  // 在应用启动时检查本地存储的认证状态
  useEffect(() => {
    checkAuthStatus();
  }, []);

  const checkAuthStatus = async () => {
    try {
      const token = localStorage.getItem('authToken');
      const savedUser = localStorage.getItem('authUser');
      
      if (token) {
        // 如果有保存的用户信息，先恢复它
        if (savedUser) {
          try {
            const parsedUser = JSON.parse(savedUser);
            setUser(parsedUser);
            setIsAuthenticated(true);
          } catch (e) {
            console.error('Failed to parse saved user:', e);
          }
        }
        
        // 验证token并获取最新的用户信息
        const userData = await authAPI.getCurrentUser();
        if (userData && userData.data && userData.data.user) {
          const transformedUser = transformUser(userData.data.user);
          setUser(transformedUser);
          setIsAuthenticated(true);
          // 更新本地存储的用户信息
          localStorage.setItem('authUser', JSON.stringify(transformedUser));
        } else {
          // Token无效，清除本地存储
          localStorage.removeItem('authToken');
          localStorage.removeItem('authUser');
          setUser(null);
          setIsAuthenticated(false);
        }
      }
    } catch (error) {
      console.error('Failed to check auth status:', error);
      // 清除无效的token和用户信息
      localStorage.removeItem('authToken');
      localStorage.removeItem('authUser');
      setUser(null);
      setIsAuthenticated(false);
    } finally {
      setLoading(false);
    }
  };

  const login = async (email: string, password: string): Promise<boolean> => {
    try {
      const response = await authAPI.login(email, password);
      
      if (response && response.data && response.data.user) {
        const transformedUser = transformUser(response.data.user);
        setUser(transformedUser);
        setIsAuthenticated(true);
        
        // 保存用户信息和token到本地存储
        localStorage.setItem('authUser', JSON.stringify(transformedUser));
        
        return true;
      }
      
      return false;
    } catch (error) {
      console.error('Login failed:', error);
      return false;
    }
  };

  const register = async (userData: {
    username: string;
    email: string;
    password: string;
    name: string;
    role: UserRole;
  }): Promise<boolean> => {
    try {
      const response = await authAPI.register(userData);
      
      if (response && response.data && response.data.user) {
        // 注册成功后自动登录
        return await login(userData.email, userData.password);
      }
      
      return false;
    } catch (error) {
      console.error('Registration failed:', error);
      return false;
    }
  };

  const logout = () => {
    // 清除API端的认证状态
    authAPI.logout();
    
    // 清除本地状态
    setUser(null);
    setIsAuthenticated(false);
    
    // 清除本地存储
    localStorage.removeItem('authUser');
    localStorage.removeItem('authToken');
  };

  const updateUser = (updatedUser: Partial<UserInfo>) => {
    if (user) {
      const newUser = { ...user, ...updatedUser };
      setUser(newUser);
      localStorage.setItem('authUser', JSON.stringify(newUser));
    }
  };

  const contextValue: AuthContextType = {
    isAuthenticated,
    user,
    loading,
    login,
    register,
    logout,
    setUser,
    updateUser,
  };

  return (
    <AuthContext.Provider value={contextValue}>
      {children}
    </AuthContext.Provider>
  );
};

// 导出useAuth hook
export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};