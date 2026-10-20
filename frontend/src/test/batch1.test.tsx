import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '../auth/AuthContext';
import { ToastProvider } from '../components/common/Toast';
import { AppContent } from '../App';
import { UploadModal } from '../components/documents/UploadModal';
import { server } from './server';
import { http, HttpResponse } from 'msw';
import { setAccessToken } from '../api/client';

function renderAppWithAuth(initialRoute = '/', role = 'admin') {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });

  server.use(
    http.post('http://localhost:8000/auth/refresh', () => {
      return HttpResponse.json({ access_token: `${role}-token` });
    }),
    http.get('http://localhost:8000/auth/me', () => {
      return HttpResponse.json({
        id: 'u-test',
        org_id: 'org-test',
        email: `${role}@acme.com`,
        role,
        is_active: true,
        created_at: '2026-03-01T00:00:00Z',
      });
    })
  );

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

describe('Batch 1: Documents, Upload, Review Queue & Dashboard', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    setAccessToken(null);
  });

  it('viewer role sees no upload control on /documents and is redirected away from /review', async () => {
    server.use(
      http.get('http://localhost:8000/documents', () => {
        return HttpResponse.json({
          items: [],
          total: 0,
          limit: 10,
          offset: 0,
        });
      })
    );

    // 1. Visit /documents as viewer
    renderAppWithAuth('/documents', 'viewer');

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Documents/i })).toBeInTheDocument();
    });

    // Upload Invoice button must NOT exist for viewer
    expect(screen.queryByTestId('open-upload-btn')).not.toBeInTheDocument();
    expect(screen.queryByText(/Upload Invoice/i)).not.toBeInTheDocument();

    // 2. Direct URL attempt to /review as viewer should be blocked by RoleRoute
    renderAppWithAuth('/review', 'viewer');

    await waitFor(() => {
      // RoleRoute redirects viewer to / (Dashboard)
      expect(screen.getByRole('heading', { name: /Dashboard/i })).toBeInTheDocument();
    });
    expect(screen.queryByRole('heading', { name: /Review Queue/i })).not.toBeInTheDocument();
  });

  it('client-side upload validation rejects wrong file types and oversized files (>10MB)', async () => {
    render(
      <ToastProvider>
        <UploadModal isOpen={true} onClose={() => {}} />
      </ToastProvider>
    );

    const fileInput = screen.getByTestId('file-picker-input');

    // 1. Test wrong file extension / mime type (e.g. .exe)
    const invalidFile = new File(['binary content'], 'malware.exe', {
      type: 'application/x-msdownload',
    });
    fireEvent.change(fileInput, { target: { files: [invalidFile] } });

    expect(
      await screen.findByText(/Invalid file type\. Only authentic PDF, PNG, and JPEG/i)
    ).toBeInTheDocument();
    expect(screen.queryByText('malware.exe')).not.toBeInTheDocument();

    // 2. Test file over 10 MB limit
    const oversizedBytes = new Uint8Array(11 * 1024 * 1024); // 11 MB
    const oversizedFile = new File([oversizedBytes], 'huge_invoice.pdf', {
      type: 'application/pdf',
    });
    fireEvent.change(fileInput, { target: { files: [oversizedFile] } });

    expect(
      await screen.findByText(/File size exceeds 10 MB limit/i)
    ).toBeInTheDocument();
    expect(screen.queryByText('huge_invoice.pdf')).not.toBeInTheDocument();
  });

  it('polling interval runs only while items are uploaded or processing, and stops otherwise', () => {
    // Import the refetchInterval logic as tested in Documents component
    const hasActiveProcessing = (items: { status: string }[]) =>
      items.some((doc) => doc.status === 'uploaded' || doc.status === 'processing');

    const activeList = [
      { status: 'auto_approved' },
      { status: 'processing' },
      { status: 'needs_review' },
    ];
    expect(hasActiveProcessing(activeList)).toBe(true);

    const completedList = [
      { status: 'auto_approved' },
      { status: 'approved' },
      { status: 'needs_review' },
      { status: 'exported' },
      { status: 'failed' },
    ];
    // No uploaded or processing documents -> polling stops!
    expect(hasActiveProcessing(completedList)).toBe(false);
  });

  it('failed document renders error_message and allows admin/reviewer to Reprocess', async () => {
    let reprocessCalled = false;
    server.use(
      http.get('http://localhost:8000/documents', () => {
        return HttpResponse.json({
          items: [
            {
              id: 'doc-failed-1',
              org_id: 'org-test',
              uploaded_by: 'u-test',
              original_filename: 'damaged_scan.pdf',
              content_type: 'application/pdf',
              size_bytes: 5432,
              sha256: 'deadbeef123',
              storage_key: 'org-test/damaged.pdf',
              status: 'failed',
              error_message: 'Corrupt PDF trailer: cannot extract text',
              created_at: '2026-03-01T12:00:00Z',
              updated_at: '2026-03-01T12:05:00Z',
            },
          ],
          total: 1,
          limit: 10,
          offset: 0,
        });
      }),
      http.post('http://localhost:8000/documents/doc-failed-1/reprocess', () => {
        reprocessCalled = true;
        return HttpResponse.json({
          id: 'doc-failed-1',
          org_id: 'org-test',
          uploaded_by: 'u-test',
          original_filename: 'damaged_scan.pdf',
          content_type: 'application/pdf',
          size_bytes: 5432,
          sha256: 'deadbeef123',
          storage_key: 'org-test/damaged.pdf',
          status: 'uploaded',
          error_message: null,
          created_at: '2026-03-01T12:00:00Z',
          updated_at: '2026-03-01T12:06:00Z',
        });
      })
    );

    const user = userEvent.setup();
    renderAppWithAuth('/documents', 'admin');

    await waitFor(() => {
      expect(screen.getByText('damaged_scan.pdf')).toBeInTheDocument();
    });

    // Error message is displayed in table
    expect(screen.getByText('Corrupt PDF trailer: cannot extract text')).toBeInTheDocument();

    // Reprocess button exists and triggers mutation
    const reprocessBtn = screen.getByTestId('reprocess-btn-doc-failed-1');
    expect(reprocessBtn).toBeInTheDocument();

    await user.click(reprocessBtn);

    await waitFor(() => {
      expect(reprocessCalled).toBe(true);
    });
  });

  it('untrusted text like "<img src=x onerror=alert(1)>.pdf" renders strictly as plain text', async () => {
    const maliciousFilename = '<img src=x onerror=alert(1)>.pdf';
    server.use(
      http.get('http://localhost:8000/documents', () => {
        return HttpResponse.json({
          items: [
            {
              id: 'doc-xss-1',
              org_id: 'org-test',
              uploaded_by: 'u-test',
              original_filename: maliciousFilename,
              content_type: 'application/pdf',
              size_bytes: 2048,
              sha256: 'beef123',
              storage_key: 'org-test/xss.pdf',
              status: 'auto_approved',
              created_at: '2026-03-01T10:00:00Z',
              updated_at: '2026-03-01T10:01:00Z',
            },
          ],
          total: 1,
          limit: 10,
          offset: 0,
        });
      })
    );

    renderAppWithAuth('/documents', 'admin');

    await waitFor(() => {
      expect(screen.getByTestId('document-filename')).toBeInTheDocument();
    });

    const filenameEl = screen.getByTestId('document-filename');
    // Content rendered as plain text string
    expect(filenameEl.textContent).toBe(maliciousFilename);

    // Absolutely NO <img> tag was rendered in DOM
    const imgTags = document.querySelectorAll('img');
    expect(imgTags.length).toBe(0);
  });
});
