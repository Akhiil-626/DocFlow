import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { api } from '../api/client';
import { parseApiError } from '../api/errors';
import { Button } from '../components/common/Button';
import { Input } from '../components/common/Input';
import { Building2, AlertCircle } from 'lucide-react';

export const Register: React.FC = () => {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [orgName, setOrgName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (password.length < 8) {
      setError('Password must be at least 8 characters long');
      return;
    }

    setIsLoading(true);

    try {
      const { error: regErr, response: regRes } = await api.POST('/auth/register', {
        body: {
          org_name: orgName,
          email,
          password,
        },
      });

      if (regErr) {
        const parsed = parseApiError(regErr, regRes?.status);
        setError(parsed.message || 'Registration failed');
        setIsLoading(false);
        return;
      }

      // Try automatic login
      const { data: loginData, error: loginErr } = await api.POST('/auth/login', {
        body: { email, password },
      });

      if (!loginErr && loginData?.access_token) {
        await login(loginData.access_token);
        navigate('/', { replace: true });
      } else {
        navigate('/login', {
          replace: true,
          state: { message: 'Organization registered successfully! Please sign in.' },
        });
      }
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
            <Building2 className="w-6 h-6" />
          </div>
          <h2 className="text-2xl font-bold text-gray-900 tracking-tight">Create an Organization</h2>
          <p className="mt-2 text-sm text-gray-600">
            Set up your organization account and initial admin user
          </p>
        </div>

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
            id="reg-org-name"
            label="Organization name"
            required
            value={orgName}
            onChange={(e) => setOrgName(e.target.value)}
            placeholder="Acme Logistics Corp"
          />

          <Input
            id="reg-email"
            label="Admin email address"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="admin@acme.com"
          />

          <Input
            id="reg-password"
            label="Password (min 8 characters)"
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            helperText="Must contain at least 8 characters"
          />

          <Button type="submit" className="w-full" isLoading={isLoading}>
            Create Organization & Sign in
          </Button>

          <div className="text-center text-sm text-gray-600">
            Already have an account?{' '}
            <Link to="/login" className="font-semibold text-sky-600 hover:text-sky-500">
              Sign in
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
};
