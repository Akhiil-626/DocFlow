import { http, HttpResponse } from 'msw';

export const mockUser = {
  id: 'a0000000-0000-0000-0000-000000000001',
  org_id: 'b0000000-0000-0000-0000-000000000001',
  email: 'admin@acme.com',
  role: 'admin',
  is_active: true,
  created_at: '2026-03-01T10:00:00Z',
};

export const handlers = [
  http.post('http://localhost:8000/auth/login', async ({ request }) => {
    const body = (await request.json()) as { email?: string; password?: string };
    if (body.email === 'wrong@acme.com') {
      return HttpResponse.json({ detail: 'Invalid credentials' }, { status: 401 });
    }
    return HttpResponse.json({
      access_token: 'mock-access-token-initial',
      token_type: 'bearer',
    });
  }),

  http.post('http://localhost:8000/auth/refresh', () => {
    return HttpResponse.json({
      access_token: 'mock-refreshed-access-token',
      token_type: 'bearer',
    });
  }),

  http.get('http://localhost:8000/auth/me', ({ request }) => {
    const authHeader = request.headers.get('Authorization');
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      return HttpResponse.json({ detail: 'Not authenticated' }, { status: 401 });
    }
    return HttpResponse.json(mockUser);
  }),

  http.post('http://localhost:8000/auth/logout', () => {
    return HttpResponse.json({ detail: 'Successfully logged out' });
  }),

  http.get('http://localhost:8000/stats', () => {
    return HttpResponse.json({
      counts: {
        auto_approved: 5,
        needs_review: 2,
        approved: 3,
        rejected: 1,
        exported: 0,
        uploaded: 0,
        processing: 0,
        failed: 1,
      },
      total: 12,
      auto_approval_rate: 0.4167,
      documents_reviewed: 4,
      approved_count: 3,
      rejected_count: 1,
      correction_rate: 0.25,
      top_corrected_fields: [
        { field: 'total', count: 3 },
        { field: 'vendor_name', count: 2 },
      ],
    });
  }),
];
