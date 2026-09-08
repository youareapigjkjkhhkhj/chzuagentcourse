import { useContext } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { AuthContext } from '../contexts/authContext';
import { MessagePlugin, Loading } from 'tdesign-react';

interface PrivateRouteProps {
  children: React.ReactNode;
  requiredRole?: 'doctor' | 'admin';
}

export default function PrivateRoute({ children, requiredRole }: PrivateRouteProps) {
  const { isAuthenticated, user, loading } = useContext(AuthContext);
  const location = useLocation();

  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f5f5f5' }}>
        <div style={{ textAlign: 'center' }}>
          <Loading size="large" />
          <p style={{ marginTop: 16, color: '#666' }}>正在验证身份...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (requiredRole && user && user.role !== requiredRole) {
    MessagePlugin.error('您没有权限访问此页面');
    return <Navigate to="/dashboard" replace />;
  }

  return <>{children}</>;
}