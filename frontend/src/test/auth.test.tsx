import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import React from 'react';
import { AuthProvider } from '../auth/AuthContext';
import { useAuth } from '../auth/useAuth';
import { getAccessToken, setAccessToken, authenticatedFetch, API_BASE_URL } from '../api/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from './server';

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    );
  };
}

const TestAuthConsumer = () => {
  const { user, isAuthenticated, isLoading, sessionExpired, logout } = useAuth();
  if (isLoading) return <div>Loading Auth...</div>;
  return (
    <div>
      <div data-testid="auth-status">{isAuthenticated ? 'authenticated' : 'unauthenticated'}</div>
      <div data-testid="user-email">{user?.email || 'none'}</div>
      <div data-testid="session-expired">{sessionExpired ? 'expired' : 'active'}</div>
      <button onClick={() => logout()}>Logout</button>
    </div>
  );
};

describe('Auth System', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    setAccessToken(null);
  });

  it('keeps access token IN MEMORY ONLY (never in localStorage or sessionStorage)', async () => {
    setAccessToken('test-secret-token');
    expect(getAccessToken()).toBe('test-secret-token');
    expect(localStorage.getItem('token')).toBeNull();
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(sessionStorage.getItem('token')).toBeNull();
  });

  it('restores session on startup using POST /auth/refresh and loads GET /auth/me', async () => {
    render(<TestAuthConsumer />, { wrapper: createWrapper() });

    expect(screen.getByText('Loading Auth...')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('authenticated');
    });

    expect(screen.getByTestId('user-email')).toHaveTextContent('admin@acme.com');
    expect(getAccessToken()).toBe('mock-refreshed-access-token');
    // Still not in localStorage
    expect(localStorage.length).toBe(0);
  });

  it('handles failed initial refresh gracefully without crashing', async () => {
    server.use(
      http.post('http://localhost:8000/auth/refresh', () => {
        return HttpResponse.json({ detail: 'No refresh token' }, { status: 401 });
      })
    );

    render(<TestAuthConsumer />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('unauthenticated');
    });

    expect(getAccessToken()).toBeNull();
    expect(screen.getByTestId('user-email')).toHaveTextContent('none');
  });

  it('executes exactly ONE single-flight refresh when several requests fail with 401 concurrently, then retries them', async () => {
    let refreshCalls = 0;
    server.use(
      http.post('http://localhost:8000/auth/refresh', () => {
        refreshCalls++;
        return HttpResponse.json({
          access_token: 'new-valid-token',
          token_type: 'bearer',
        });
      }),
      http.get('http://localhost:8000/test-endpoint-1', ({ request }) => {
        const auth = request.headers.get('Authorization');
        if (auth === 'Bearer new-valid-token') {
          return HttpResponse.json({ result: 'success-1' });
        }
        return HttpResponse.json({ detail: 'Token expired' }, { status: 401 });
      }),
      http.get('http://localhost:8000/test-endpoint-2', ({ request }) => {
        const auth = request.headers.get('Authorization');
        if (auth === 'Bearer new-valid-token') {
          return HttpResponse.json({ result: 'success-2' });
        }
        return HttpResponse.json({ detail: 'Token expired' }, { status: 401 });
      }),
      http.get('http://localhost:8000/test-endpoint-3', ({ request }) => {
        const auth = request.headers.get('Authorization');
        if (auth === 'Bearer new-valid-token') {
          return HttpResponse.json({ result: 'success-3' });
        }
        return HttpResponse.json({ detail: 'Token expired' }, { status: 401 });
      })
    );

    // Initial state: old expired token
    setAccessToken('expired-token');

    // Fire 3 requests concurrently
    const [res1, res2, res3] = await Promise.all([
      authenticatedFetch(`${API_BASE_URL}/test-endpoint-1`),
      authenticatedFetch(`${API_BASE_URL}/test-endpoint-2`),
      authenticatedFetch(`${API_BASE_URL}/test-endpoint-3`),
    ]);

    expect(res1.status).toBe(200);
    expect(res2.status).toBe(200);
    expect(res3.status).toBe(200);

    const [data1, data2, data3] = await Promise.all([res1.json(), res2.json(), res3.json()]);
    expect(data1.result).toBe('success-1');
    expect(data2.result).toBe('success-2');
    expect(data3.result).toBe('success-3');

    // Exactly one refresh was fired!
    expect(refreshCalls).toBe(1);
    expect(getAccessToken()).toBe('new-valid-token');
  });

  it('failed refresh sets sessionExpired=true and clears in-memory token', async () => {
    server.use(
      http.post('http://localhost:8000/auth/refresh', () => {
        return HttpResponse.json({ detail: 'Token revoked' }, { status: 401 });
      }),
      http.get('http://localhost:8000/protected', () => {
        return HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 });
      })
    );

    render(<TestAuthConsumer />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('unauthenticated');
    });

    // Manually trigger a 401 request
    await act(async () => {
      await authenticatedFetch(`${API_BASE_URL}/protected`);
    });

    await waitFor(() => {
      expect(screen.getByTestId('session-expired')).toHaveTextContent('expired');
    });
    expect(getAccessToken()).toBeNull();
  });
});
