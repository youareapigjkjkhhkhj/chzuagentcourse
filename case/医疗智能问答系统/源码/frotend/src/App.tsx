import { Routes, Route } from "react-router-dom";
import Home from "@/pages/Home";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import { AuthProvider } from '@/contexts/authContext';
import { ModelContextProvider } from '@/contexts/modelContext';
import { KnowledgeBaseContextProvider } from '@/contexts/knowledgeBaseContext';
import Dashboard from "@/pages/Dashboard";
import ImageAnalysis from "@/pages/ImageAnalysis";
import ReportList from "@/pages/ReportList";
import ReportDetail from "@/pages/ReportDetail";
import UserManagement from "@/pages/UserManagement";
import SystemSettings from "@/pages/SystemSettings";
import Profile from "@/pages/Profile";
import KnowledgeBaseList from "@/pages/KnowledgeBaseList";
import DocumentManagement from "@/pages/DocumentManagement";
import KnowledgeBaseSettings from "@/pages/KnowledgeBaseSettings";
import AIAssistant from "@/pages/AIAssistant";
import ModelManager from "@/pages/ModelManager";
import ChatHistory from "@/pages/ChatHistory";
import PrivateRoute from "@/components/PrivateRoute";

export default function App() {
  return (
    <AuthProvider>
      <ModelContextProvider>
        <KnowledgeBaseContextProvider>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route 
              path="/dashboard" 
              element={
                <PrivateRoute>
                  <Dashboard />
                </PrivateRoute>
              } 
            />
            <Route 
              path="/analysis" 
              element={
                <PrivateRoute>
                  <ImageAnalysis />
                </PrivateRoute>
              } 
            />
            <Route 
              path="/reports" 
              element={
                <PrivateRoute>
                  <ReportList />
                </PrivateRoute>
              } 
            />
            <Route 
              path="/reports/:id" 
              element={
                <PrivateRoute>
                  <ReportDetail />
                </PrivateRoute>
              } 
            />
            <Route 
              path="/users" 
              element={
                <PrivateRoute requiredRole="admin">
                  <UserManagement />
                </PrivateRoute>
              } 
            />
            <Route 
              path="/settings" 
              element={
                <PrivateRoute requiredRole="admin">
                  <SystemSettings />
                </PrivateRoute>
              } 
            />
            <Route 
              path="/profile" 
              element={
                <PrivateRoute>
                  <Profile />
                </PrivateRoute>
              } 
            />
            <Route 
              path="/knowledge" 
              element={
                <PrivateRoute>
                  <KnowledgeBaseList />
                </PrivateRoute>
              } 
            />
            <Route 
              path="/knowledge/:kbId" 
              element={
                <PrivateRoute>
                  <DocumentManagement />
                </PrivateRoute>
              } 
            />
            <Route 
              path="/knowledge-settings" 
              element={
                <PrivateRoute requiredRole="admin">
                  <KnowledgeBaseSettings />
                </PrivateRoute>
              } 
            />
            <Route 
              path="/ai-assistant" 
              element={
                <PrivateRoute>
                  <AIAssistant />
                </PrivateRoute>
              } 
            />
            <Route 
              path="/models" 
              element={
                <PrivateRoute requiredRole="admin">
                  <ModelManager />
                </PrivateRoute>
              } 
            />
            <Route 
              path="/chat-history" 
              element={
                <PrivateRoute>
                  <ChatHistory />
                </PrivateRoute>
              } 
            />
          </Routes>
        </KnowledgeBaseContextProvider>
      </ModelContextProvider>
    </AuthProvider>
  );
}
