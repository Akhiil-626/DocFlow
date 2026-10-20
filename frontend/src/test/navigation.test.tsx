import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '../auth/AuthContext';
import { ToastProvider } from '../components/common/Toast';
import { AppContent } from '../App';
import { server } from './server';
import { http, HttpResponse } from 'msw';
import { setAccessToken } from '../api/client';

function renderApp(initialRoute = '/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[initialRoute]}>
            <AppContent />
          </MemoryRouter>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}

describe('Navigation & Auth Flows', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    setAccessToken(null);
  });

  it('unauthenticated user is redirected to /login', async () => {
    server.use(
      http.post('http://localhost:8000/auth/refresh', () => {
        return HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 });
      })
    );

    renderApp('/');

    await waitFor(() => {
      expect(screen.getByText('Sign in to DocFlow')).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/Email address/)).toBeInTheDocument();
  });

  it('successful login submits credentials and navigates to Dashboard', async () => {
    server.use(
      http.post('http://localhost:8000/auth/refresh', () => {
        return HttpResponse.json({ detail: 'No session' }, { status: 401 });
      }),
      http.post('http://localhost:8000/auth/login', async () => {
        return HttpResponse.json({
          access_token: 'valid-test-token',
          token_type: 'bearer',
        });
      }),
      http.get('http://localhost:8000/auth/me', () => {
        return HttpResponse.json({
          id: 'u-1',
          org_id: 'org-1',
          email: 'admin@acme.com',
          role: 'admin',
          is_active: true,
          created_at: '2026-03-01T00:00:00Z',
        });
      })
    );

    const user = userEvent.setup();
    renderApp('/login');

    await waitFor(() => {
      expect(screen.getByText('Sign in to DocFlow')).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText(/Email address/), 'admin@acme.com');
    await user.type(screen.getByLabelText(/Password/), 'password123');
    await user.click(screen.getByRole('button', { name: /Sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Dashboard/i })).toBeInTheDocument();
      expect(screen.getByText('admin@acme.com')).toBeInTheDocument();
    });
  });

  it('viewer role does not see Review Queue nav item', async () => {
    server.use(
      http.post('http://localhost:8000/auth/refresh', () => {
        return HttpResponse.json({ access_token: 'viewer-token' });
      }),
      http.get('http://localhost:8000/auth/me', () => {
        return HttpResponse.json({
          id: 'u-2',
          org_id: 'org-1',
          email: 'viewer@acme.com',
          role: 'viewer',
          is_active: true,
          created_at: '2026-03-01T00:00:00Z',
        });
      })
    );

    renderApp('/');

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Dashboard/i })).toBeInTheDocument();
    });

    expect(screen.getByText('viewer@acme.com')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Documents/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Exports/i })).toBeInTheDocument();
    // Viewer must NOT see Review Queue link
    expect(screen.queryByRole('link', { name: /Review Queue/i })).not.toBeInTheDocument();
  });

  it('reviewer role sees Review Queue nav item', async () => {
    server.use(
      http.post('http://localhost:8000/auth/refresh', () => {
        return HttpResponse.json({ access_token: 'reviewer-token' });
      }),
      http.get('http://localhost:8000/auth/me', () => {
        return HttpResponse.json({
          id: 'u-3',
          org_id: 'org-1',
          email: 'reviewer@acme.com',
          role: 'reviewer',
          is_active: true,
          created_at: '2026-03-01T00:00:00Z',
        });
      })
    );

    renderApp('/');

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Dashboard/i })).toBeInTheDocument();
    });

    expect(screen.getByRole('link', { name: /Review Queue/i })).toBeInTheDocument();
  });

  it('clicking Logout logs out and returns to /login', async () => {
    server.use(
      http.post('http://localhost:8000/auth/refresh', () => {
        return HttpResponse.json({ access_token: 'admin-token' });
      }),
      http.get('http://localhost:8000/auth/me', () => {
        return HttpResponse.json({
          id: 'u-1',
          org_id: 'org-1',
          email: 'admin@acme.com',
          role: 'admin',
          is_active: true,
          created_at: '2026-03-01T00:00:00Z',
        });
      }),
      http.post('http://localhost:8000/auth/logout', () => {
        return HttpResponse.json({ detail: 'Logged out' });
      })
    );

    const user = userEvent.setup();
    renderApp('/');

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Dashboard/i })).toBeInTheDocument();
    });

    const logoutBtn = screen.getByRole('button', { name: /log out/i });
    await user.click(logoutBtn);

    await waitFor(() => {
      expect(screen.getByText('Sign in to DocFlow')).toBeInTheDocument();
    });
  });
});
