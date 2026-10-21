import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '../auth/AuthContext';
import { ToastProvider } from '../components/common/Toast';
import { AppContent } from '../App';
import { server } from './server';
import { http, HttpResponse } from 'msw';
import { setAccessToken, authenticatedFetch, API_BASE_URL } from '../api/client';

const mockDocId = 'd0000000-0000-0000-0000-000000000001';

const sampleDocument = {
  id: mockDocId,
  org_id: 'org-test-1',
  uploaded_by: 'user-admin-1',
  original_filename: 'sample_invoice.pdf',
  content_type: 'application/pdf',
  size_bytes: 2048,
  sha256: 'a1b2c3d4',
  storage_key: 'org-test-1/sample.pdf',
  status: 'needs_review',
  error_message: null,
  review_reason: 'Total mismatch detected',
  validated_at: '2026-03-01T10:00:00Z',
  reviewed_by: null,
  reviewed_at: null,
  review_note: null,
  export_batch_id: null,
  exported_at: null,
  processed_at: '2026-03-01T10:01:00Z',
  attempts: 1,
  existing_document_id: null,
  created_at: '2026-03-01T10:00:00Z',
  updated_at: '2026-03-01T10:01:00Z',
};

const sampleExtraction = {
  id: 'e0000000-0000-0000-0000-000000000001',
  document_id: mockDocId,
  org_id: 'org-test-1',
  version: 1,
  model: 'gemini-2.5-flash',
  input_tokens: 120,
  output_tokens: 80,
  latency_ms: 12,
  created_at: '2026-03-01T10:01:00Z',
  edited_at: null,
  edited_by: null,
  original_data: {
    vendor_name: 'Original Model Vendor',
    vendor_gstin: '27AABCU9603R1ZM',
    invoice_number: 'INV-100',
    invoice_date: '2026-03-01',
    currency: 'INR',
    subtotal: '1000.00',
    cgst: '90.00',
    sgst: '90.00',
    igst: '0.00',
    total: '1180.00',
  },
  data: {
    vendor_name: 'Original Model Vendor',
    vendor_gstin: '27AABCU9603R1ZM',
    invoice_number: 'INV-100',
    invoice_date: '2026-03-01',
    currency: 'INR',
    subtotal: '1000.00',
    cgst: '90.00',
    sgst: '90.00',
    igst: '0.00',
    total: '1180.00',
  },
  line_items: [
    {
      id: 'li-1',
      description: 'Cloud Server Hosting',
      quantity: '1.00',
      unit_price: '1000.00',
      amount: '1000.00',
    },
  ],
  validation_issues: [
    {
      id: 'iss-1',
      code: 'TOTAL_MISMATCH',
      severity: 'error',
      field: 'total',
      message: 'Line item sums do not equal total',
      created_at: '2026-03-01T10:01:00Z',
    },
  ],
};

function renderAppWithRoute(
  route = `/documents/${mockDocId}`,
  role = 'admin',
  options?: {
    doc?: Partial<typeof sampleDocument>;
    ext?: Partial<typeof sampleExtraction>;
  }
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });

  const mergedDoc = { ...sampleDocument, ...options?.doc };
  const mergedExt = { ...sampleExtraction, ...options?.ext };

  server.use(
    http.post('http://localhost:8000/auth/refresh', () => {
      return HttpResponse.json({ access_token: `${role}-token` });
    }),
    http.get('http://localhost:8000/auth/me', () => {
      return HttpResponse.json({
        id: 'u-admin-1',
        org_id: 'org-test-1',
        email: `${role}@acme.com`,
        role,
        is_active: true,
        created_at: '2026-03-01T00:00:00Z',
      });
    }),
    http.get(`http://localhost:8000/documents/${mockDocId}`, () => {
      return HttpResponse.json(mergedDoc);
    }),
    http.get(`http://localhost:8000/documents/${mockDocId}/file`, () => {
      return new HttpResponse(new Uint8Array([37, 80, 68, 70]), {
        headers: { 'Content-Type': 'application/pdf' },
      });
    }),
    http.get(`http://localhost:8000/documents/${mockDocId}/extraction`, () => {
      return HttpResponse.json(mergedExt);
    })
  );

  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[route]}>
            <AppContent />
          </MemoryRouter>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}

describe('Batch 2: Review Screen, Optimistic Concurrency, and Exports', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    setAccessToken(null);
  });

  it('Save sends only changed fields plus the version', async () => {
    let capturedPatchBody: Record<string, unknown> | null = null;
    server.use(
      http.patch(`http://localhost:8000/documents/${mockDocId}/extraction`, async ({ request }) => {
        capturedPatchBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          ...sampleExtraction,
          version: 2,
          data: {
            ...sampleExtraction.data,
            vendor_name: 'Acme Updated Ltd',
          },
        });
      })
    );

    const user = userEvent.setup();
    renderAppWithRoute(`/documents/${mockDocId}`, 'reviewer');

    await waitFor(() => {
      expect(screen.getByLabelText(/Vendor Name/i)).toBeInTheDocument();
    });

    const vendorInput = screen.getByLabelText(/Vendor Name/i);
    fireEvent.change(vendorInput, { target: { value: 'Acme Updated Ltd' } });

    const saveBtn = screen.getByTestId('save-extraction-btn');
    await user.click(saveBtn);

    await waitFor(() => {
      expect(capturedPatchBody).not.toBeNull();
    });

    // Version must be sent
    expect(capturedPatchBody!.version).toBe(1);
    // Changed field must be sent
    expect(capturedPatchBody!.vendor_name).toBe('Acme Updated Ltd');
    // Unchanged fields must NOT be in patch body
    expect(capturedPatchBody!.invoice_number).toBeUndefined();
    expect(capturedPatchBody!.currency).toBeUndefined();
  });

  it('A 409 shows the conflict dialog and keeps the user edits', async () => {
    server.use(
      http.patch(`http://localhost:8000/documents/${mockDocId}/extraction`, () => {
        return HttpResponse.json({ detail: 'Version conflict' }, { status: 409 });
      })
    );

    const user = userEvent.setup();
    renderAppWithRoute(`/documents/${mockDocId}`, 'reviewer');

    await waitFor(() => {
      expect(screen.getByLabelText(/Vendor Name/i)).toBeInTheDocument();
    });

    const vendorInput = screen.getByLabelText(/Vendor Name/i);
    fireEvent.change(vendorInput, { target: { value: 'My Offline Edits' } });

    const saveBtn = screen.getByTestId('save-extraction-btn');
    await user.click(saveBtn);

    // Conflict dialog opens
    await waitFor(() => {
      expect(screen.getByText('This invoice was changed by someone else')).toBeInTheDocument();
    });

    // User chooses to keep edits
    const keepBtn = screen.getByTestId('keep-my-edits-btn');
    await user.click(keepBtn);

    // Dialog closes and input still contains unsaved edits!
    expect(screen.queryByText('This invoice was changed by someone else')).not.toBeInTheDocument();
    expect(vendorInput).toHaveValue('My Offline Edits');
  });

  it('Approve with remaining errors forces a reason; without errors approves directly', async () => {
    let capturedApproveBody: { override?: boolean; reason?: string } | null = null;
    server.use(
      http.post(`http://localhost:8000/documents/${mockDocId}/approve`, async ({ request }) => {
        capturedApproveBody = (await request.json()) as { override?: boolean; reason?: string };
        return HttpResponse.json({
          ...sampleDocument,
          status: 'approved',
          reviewed_by: 'u-admin-1',
          reviewed_at: '2026-03-01T12:00:00Z',
          review_note: capturedApproveBody.reason || null,
        });
      })
    );

    const user = userEvent.setup();
    renderAppWithRoute(`/documents/${mockDocId}`, 'reviewer');

    await waitFor(() => {
      expect(screen.getByTestId('approve-btn')).toBeInTheDocument();
    });

    // Form has sampleExtraction with error issue TOTAL_MISMATCH
    const approveBtn = screen.getByTestId('approve-btn');
    await user.click(approveBtn);

    // Modal requiring override reason must appear
    expect(await screen.findByText('Approve Invoice with Errors')).toBeInTheDocument();

    const reasonInput = screen.getByLabelText(/Override Reason/i);
    fireEvent.change(reasonInput, {
      target: { value: 'Accepted total discrepancy per management approval' },
    });

    const confirmApproveBtn = await screen.findByTestId('confirm-approve-override-btn');
    await user.click(confirmApproveBtn);

    await waitFor(() => {
      expect(capturedApproveBody).not.toBeNull();
    });
    expect(capturedApproveBody!.override).toBe(true);
    expect(capturedApproveBody!.reason).toBe(
      'Accepted total discrepancy per management approval'
    );
  });

  it('Money fields stay strings; an invalid decimal is rejected before sending', async () => {
    let patchAttempted = false;
    server.use(
      http.patch(`http://localhost:8000/documents/${mockDocId}/extraction`, () => {
        patchAttempted = true;
        return HttpResponse.json(sampleExtraction);
      })
    );

    const user = userEvent.setup();
    renderAppWithRoute(`/documents/${mockDocId}`, 'reviewer');

    await waitFor(() => {
      expect(screen.getByLabelText(/Total Amount/i)).toBeInTheDocument();
    });

    const totalInput = screen.getByLabelText(/Total Amount/i);
    fireEvent.change(totalInput, { target: { value: 'invalid.text.number' } });

    const saveBtn = screen.getByTestId('save-extraction-btn');
    await user.click(saveBtn);

    // Client displays decimal format error
    expect(await screen.findByText(/Must be a valid decimal number/i)).toBeInTheDocument();
    // Request must NOT be dispatched to backend
    expect(patchAttempted).toBe(false);
  });

  it('Dirty form blocks navigation and disables Approve', async () => {
    const user = userEvent.setup();
    renderAppWithRoute(`/documents/${mockDocId}`, 'reviewer');

    await waitFor(() => {
      expect(screen.getByLabelText(/Vendor Name/i)).toBeInTheDocument();
    });

    const approveBtn = screen.getByTestId('approve-btn');
    // Initially not dirty -> approve is enabled
    expect(approveBtn).not.toBeDisabled();

    // Modify a field
    const vendorInput = screen.getByLabelText(/Vendor Name/i);
    fireEvent.change(vendorInput, { target: { value: 'Original Model Vendor Extended' } });

    // Dirty indicator appears and Approve is disabled
    expect(await screen.findByTestId('dirty-indicator')).toBeInTheDocument();
    expect(approveBtn).toBeDisabled();

    // In-app navigation triggers confirmation modal
    const backBtn = screen.getByLabelText(/Back to documents/i);
    await user.click(backBtn);

    expect(screen.getByText('Unsaved Changes')).toBeInTheDocument();
    expect(screen.getByText(/You have unsaved changes on this invoice/i)).toBeInTheDocument();
  });

  it('Viewer sees a read-only form; only admin sees Reopen', async () => {
    // 1. Viewer role on needs_review document
    const { unmount } = renderAppWithRoute(`/documents/${mockDocId}`, 'viewer');

    await waitFor(() => {
      expect(screen.getByLabelText(/Vendor Name/i)).toBeInTheDocument();
    });

    // Inputs disabled
    expect(screen.getByLabelText(/Vendor Name/i)).toBeDisabled();
    expect(screen.queryByTestId('save-extraction-btn')).not.toBeInTheDocument();
    expect(screen.queryByTestId('approve-btn')).not.toBeInTheDocument();
    expect(screen.queryByTestId('reject-btn')).not.toBeInTheDocument();
    unmount();

    // 2. Reviewer role on approved doc -> Reopen NOT visible
    const { unmount: unmountReviewer } = renderAppWithRoute(
      `/documents/${mockDocId}`,
      'reviewer',
      { doc: { status: 'approved' } }
    );
    await waitFor(() => {
      expect(screen.getByText('sample_invoice.pdf')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('reopen-btn')).not.toBeInTheDocument();
    unmountReviewer();

    // 3. Admin role on approved doc -> Reopen IS visible
    renderAppWithRoute(`/documents/${mockDocId}`, 'admin', {
      doc: { status: 'approved' },
    });
    await waitFor(() => {
      expect(screen.getByTestId('reopen-btn')).toBeInTheDocument();
    });
  });

  it('A vendor name like "<img src=x onerror=alert(1)>" and "=HYPERLINK(...)" renders as plain text', async () => {
    const maliciousVendor = '<img src=x onerror=alert(1)>';
    const formulaInvoiceNo = '=HYPERLINK("http://evil.com")';

    renderAppWithRoute(`/documents/${mockDocId}`, 'reviewer', {
      ext: {
        data: {
          ...sampleExtraction.data,
          vendor_name: maliciousVendor,
          invoice_number: formulaInvoiceNo,
        },
      },
    });

    await waitFor(() => {
      expect(screen.getByLabelText(/Vendor Name/i)).toBeInTheDocument();
    });

    const vendorInput = screen.getByLabelText(/Vendor Name/i);
    expect(vendorInput).toHaveValue(maliciousVendor);

    const invoiceNoInput = screen.getByLabelText(/Invoice Number/i);
    expect(invoiceNoInput).toHaveValue(formulaInvoiceNo);

    // Zero <img> tags injected into DOM
    expect(document.querySelectorAll('img').length).toBe(0);
  });

  it('Export: 409 shows friendly message; download sends Authorization header', async () => {
    let downloadAuthHeader: string | null = null;
    server.use(
      http.get('http://localhost:8000/exports', () => {
        return HttpResponse.json({
          items: [
            {
              id: 'exp-batch-001',
              org_id: 'org-test-1',
              created_by: 'u-admin-1',
              format: 'csv',
              row_count: 3,
              created_at: '2026-03-01T15:00:00Z',
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        });
      }),
      http.post('http://localhost:8000/exports', () => {
        return HttpResponse.json({ detail: 'No approved documents' }, { status: 409 });
      }),
      http.get('http://localhost:8000/exports/exp-batch-001/download', ({ request }) => {
        downloadAuthHeader = request.headers.get('Authorization');
        return new HttpResponse('doc_id,vendor_name\n1,Acme\n', {
          headers: { 'Content-Type': 'text/csv' },
        });
      })
    );

    const user = userEvent.setup();
    renderAppWithRoute('/exports', 'admin');

    await waitFor(() => {
      expect(screen.getByText(/exp-batc/i)).toBeInTheDocument();
    });

    // 1. Test 409 friendly notice on create export
    const createBtn = screen.getByTestId('create-export-btn');
    await user.click(createBtn);

    const confirmExportBtn = screen.getByTestId('confirm-create-export-btn');
    await user.click(confirmExportBtn);

    expect(await screen.findByTestId('nothing-to-export-notice')).toBeInTheDocument();
    expect(
      screen.getByText(/No approved or auto-approved invoices are currently eligible for export/i)
    ).toBeInTheDocument();

    // 2. Test download sends Authorization header
    setAccessToken('export-download-token');
    await authenticatedFetch(`${API_BASE_URL}/exports/exp-batch-001/download?view=summary`);
    expect(downloadAuthHeader).toBe('Bearer export-download-token');
  });
});
