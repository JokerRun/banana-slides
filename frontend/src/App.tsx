import { ReactElement, useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { getAuthMe } from './api/endpoints';
import { Home } from './pages/Home';
import { Landing } from './pages/Landing';
import { History } from './pages/History';
import { OutlineEditor } from './pages/OutlineEditor';
import { DetailEditor } from './pages/DetailEditor';
import { SlidePreview } from './pages/SlidePreview';
import { Login } from './pages/Login';
import { useProjectStore } from './store/useProjectStore';
import { useToast } from './components/shared';

type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

interface RequireAuthProps {
  authStatus: AuthStatus;
  children: ReactElement;
}

function RequireAuth({ authStatus, children }: RequireAuthProps) {
  if (authStatus !== 'authenticated') {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function App() {
  const { currentProject, syncProject, error, setError } = useProjectStore();
  const { show, ToastContainer } = useToast();
  const [authStatus, setAuthStatus] = useState<AuthStatus>('loading');

  useEffect(() => {
    let cancelled = false;

    const bootstrapAuth = async () => {
      try {
        const response = await getAuthMe();
        const user = response.data?.user;
        if (!cancelled) {
          setAuthStatus(user && user.is_active ? 'authenticated' : 'unauthenticated');
        }
      } catch {
        if (!cancelled) {
          setAuthStatus('unauthenticated');
        }
      }
    };

    bootstrapAuth();
    return () => {
      cancelled = true;
    };
  }, []);

  // 恢复项目状态
  useEffect(() => {
    if (authStatus !== 'authenticated') {
      return;
    }

    const savedProjectId = localStorage.getItem('currentProjectId');
    if (savedProjectId && !currentProject) {
      syncProject();
    }
  }, [authStatus, currentProject, syncProject]);

  // 显示全局错误
  useEffect(() => {
    if (error) {
      show({ message: error, type: 'error' });
      setError(null);
    }
  }, [error, setError, show]);

  if (authStatus === 'loading') {
    return null;
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={authStatus === 'authenticated' ? <Navigate to="/" replace /> : <Login />} />
        <Route path="/landing" element={<Landing />} />
        <Route path="/" element={<RequireAuth authStatus={authStatus}><Home /></RequireAuth>} />
        <Route path="/history" element={<RequireAuth authStatus={authStatus}><History /></RequireAuth>} />
        <Route path="/project/:projectId/outline" element={<RequireAuth authStatus={authStatus}><OutlineEditor /></RequireAuth>} />
        <Route path="/project/:projectId/detail" element={<RequireAuth authStatus={authStatus}><DetailEditor /></RequireAuth>} />
        <Route path="/project/:projectId/preview" element={<RequireAuth authStatus={authStatus}><SlidePreview /></RequireAuth>} />
        <Route path="*" element={<Navigate to={authStatus === 'authenticated' ? '/' : '/login'} replace />} />
      </Routes>
      <ToastContainer />
    </BrowserRouter>
  );
}

export default App;
