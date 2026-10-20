import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { api } from '../api/client';
import { parseApiError } from '../api/errors';
import { Button } from '../components/common/Button';
import { Input } from '../components/common/Input';
import { FileText, AlertCircle } from 'lucide-react';

export const Login: React.FC = () => {
  const { login, isAuthenticated, sessionExpired, clearSessionExpired } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const registeredMessage = (location.state as { message?: string } | undefined)?.message;

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/', { replace: true });
    }
  }, [isAuthenticated, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);

    try {
      const { data, error: apiErr, response } = await api.POST('/auth/login', {
        body: { email, password },
      });

      if (apiErr || !data?.access_token) {
        const parsed = parseApiError(apiErr, response?.status);
        setError(parsed.message || 'Invalid email or password');
        return;
      }

      await login(data.access_token);
      clearSessionExpired();
      navigate('/', { replace: true });
    } catch (err) {
      const parsed = parseApiError(err);
      setError(parsed.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8 bg-white p-8 rounded-2xl shadow-sm border border-gray-200/80">
        <div className="text-center">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-sky-50 text-sky-600 mb-4">
            <FileText className="w-6 h-6" />
          </div>
          <h2 className="text-2xl font-bold text-gray-900 tracking-tight">Sign in to DocFlow</h2>
          <p className="mt-2 text-sm text-gray-600">
            Intelligent invoice processing & review
          </p>
        </div>

        {sessionExpired && (
          <div
            className="p-3 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg text-sm flex items-center gap-2"
            role="alert"
          >
            <AlertCircle className="w-4 h-4 shrink-0 text-amber-600" />
            <span>Your session has expired. Please log in again to continue.</span>
          </div>
        )}

        {registeredMessage && (
          <div
            className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-lg text-sm"
            role="status"
          >
            {registeredMessage}
          </div>
        )}

        {error && (
          <div
            className="p-3 bg-rose-50 border border-rose-200 text-rose-800 rounded-lg text-sm flex items-center gap-2"
            role="alert"
          >
            <AlertCircle className="w-4 h-4 shrink-0 text-rose-600" />
            <span>{error}</span>
          </div>
        )}

        <form className="mt-8 space-y-5" onSubmit={handleSubmit} noValidate>
          <Input
            id="login-email"
            label="Email address"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.com"
          />

          <Input
            id="login-password"
            label="Password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
          />

          <Button type="submit" className="w-full" isLoading={isLoading}>
            Sign in
          </Button>

          <div className="text-center text-sm text-gray-600">
            Don&apos;t have an organization account?{' '}
            <Link to="/register" className="font-semibold text-sky-600 hover:text-sky-500">
              Register now
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
};
