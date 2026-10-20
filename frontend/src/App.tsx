import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './auth/useAuth';
import { ToastProvider } from './components/common/Toast';
import { LoadingScreen } from './components/common/LoadingScreen';
import { AppLayout } from './components/layout/AppLayout';
import { Login } from './pages/Login';
import { Register } from './pages/Register';
import { Dashboard } from './pages/Dashboard';
import { Documents } from './pages/Documents';
import { ReviewQueue } from './pages/ReviewQueue';
import { ReviewScreen } from './pages/ReviewScreen';
import { Exports } from './pages/Exports';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return <LoadingScreen message="Restoring DocFlow session..." />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
};

const RoleRoute: React.FC<{
  allowedRoles: ('admin' | 'reviewer' | 'viewer')[];
  children: React.ReactNode;
}> = ({ allowedRoles, children }) => {
  const { role, isLoading } = useAuth();

  if (isLoading) {
    return <LoadingScreen message="Checking permissions..." />;
  }

  if (!role || !allowedRoles.includes(role)) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
};

export const AppContent: React.FC = () => {
  const { isLoading } = useAuth();

  if (isLoading) {
    return <LoadingScreen message="Connecting to DocFlow..." />;
  }

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />

      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="documents" element={<Documents />} />
        <Route path="documents/:id" element={<ReviewScreen />} />
        <Route
          path="review"
          element={
            <RoleRoute allowedRoles={['admin', 'reviewer']}>
              <ReviewQueue />
            </RoleRoute>
          }
        />
        <Route path="exports" element={<Exports />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ToastProvider>
          <BrowserRouter>
            <AppContent />
          </BrowserRouter>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
};

export default App;
