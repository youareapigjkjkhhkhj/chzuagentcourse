import React, { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { authAPI, transformUser } from '../services/api';

export type UserRole = 'doctor' | 'admin';

export interface UserInfo {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  lastLogin?: string;
}

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
}

export const AuthContext = createContext<AuthContextType>({
  isAuthenticated: false,
  user: null,
  loading: true,
  login: async () => false,
  register: async () => false,
  logout: () => {},
  setUser: () => {},
});

interface AuthProviderProps {
  children: ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    checkAuthStatus();
  }, []);

  const checkAuthStatus = async () => {
    try {
      const token = localStorage.getItem('authToken');
      if (token) {
        const userData = await authAPI.getCurrentUser();
        if (userData && userData.success && userData.data && userData.data.user) {
          setUser(transformUser(userData.data.user));
          setIsAuthenticated(true);
        } else {
          localStorage.removeItem('authToken');
        }
      }
    } catch (error) {
      console.error('Failed to check auth status:', error);
      localStorage.removeItem('authToken');
    } finally {
      setLoading(false);
    }
  };

  const login = async (email: string, password: string): Promise<boolean> => {
    try {
      const response = await authAPI.login(email, password);
      
      if (response && response.success && response.data && response.data.user) {
        const transformedUser = transformUser(response.data.user);
        setUser(transformedUser);
        setIsAuthenticated(true);
        
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
      
      if (response && response.success && response.data && response.data.user) {
        return await login(userData.email, userData.password);
      }
      
      return false;
    } catch (error) {
      console.error('Registration failed:', error);
      return false;
    }
  };

  const logout = () => {
    authAPI.logout();
    
    setUser(null);
    setIsAuthenticated(false);
    
    localStorage.removeItem('authUser');
    localStorage.removeItem('authToken');
  };

  const contextValue: AuthContextType = {
    isAuthenticated,
    user,
    loading,
    login,
    register,
    logout,
    setUser,
  };

  return (
    React.createElement(AuthContext.Provider, { value: contextValue }, children)
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};