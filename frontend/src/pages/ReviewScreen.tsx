import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { parseApiError } from '../api/errors';
import { useAuth } from '../auth/useAuth';
import { useToast } from '../components/common/useToast';
import { StatusBadge } from '../components/common/StatusBadge';
import { Button } from '../components/common/Button';
import { Input } from '../components/common/Input';
import { Modal } from '../components/common/Modal';
import { DocumentViewer } from '../components/review/DocumentViewer';
import { IssuesPanel } from '../components/review/IssuesPanel';
import { HistoryDrawer } from '../components/review/HistoryDrawer';
import { ConflictModal } from '../components/review/ConflictModal';
import {
  Save,
  CheckCircle2,
  XCircle,
  RotateCcw,
  History,
  Plus,
  Trash2,
  AlertCircle,
  RefreshCw,
  FileText,
  Shield,
  ArrowLeft,
} from 'lucide-react';
import type { paths } from '../api/schema';

type DocumentResponse =
  paths['/documents/{document_id}']['get']['responses'][200]['content']['application/json'];
type ExtractionResponse =
  paths['/documents/{document_id}/extraction']['get']['responses'][200]['content']['application/json'];

interface LineItemFormState {
  id?: string;
  description: string;
  quantity: string;
  unit_price: string;
  amount: string;
}

interface HeaderFormState {
  vendor_name: string;
  vendor_gstin: string;
  invoice_number: string;
  invoice_date: string;
  currency: string;
  subtotal: string;
  cgst: string;
  sgst: string;
  igst: string;
  total: string;
  note: string;
}

const DECIMAL_REGEX = /^-?\d+(\.\d+)?$/;

export const ReviewScreen: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { role } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();

  const isReviewerOrAdmin = role === 'admin' || role === 'reviewer';

  // Responsive tabs for narrow viewports
  const [activeTab, setActiveTab] = useState<'preview' | 'details'>('details');

  // Modals state
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [isConflictOpen, setIsConflictOpen] = useState(false);
  const [isApproveModalOpen, setIsApproveModalOpen] = useState(false);
  const [isRejectModalOpen, setIsRejectModalOpen] = useState(false);
  const [isReopenModalOpen, setIsReopenModalOpen] = useState(false);
  const [isUnsavedLeaveModalOpen, setIsUnsavedLeaveModalOpen] = useState(false);
  const [pendingNavigateTo, setPendingNavigateTo] = useState<string | null>(null);

  // Form reasons
  const [overrideReason, setOverrideReason] = useState('');
  const [rejectReason, setRejectReason] = useState('');

  // Form inputs reference map for smooth scroll and focus
  const inputRefs = useRef<Record<string, HTMLInputElement | null>>({});

  // 1. Fetch document metadata
  const {
    data: documentData,
    isLoading: isDocLoading,
    isError: isDocError,
    error: docError,
    refetch: refetchDoc,
  } = useQuery<DocumentResponse>({
    queryKey: ['document', id],
    queryFn: async () => {
      const { data, error: apiErr, response } = await api.GET(
        '/documents/{document_id}',
        {
          params: { path: { document_id: id! } },
        }
      );
      if (apiErr || !data) {
        throw parseApiError(apiErr, response?.status);
      }
      return data;
    },
    enabled: !!id,
  });

  // 2. Fetch extraction data
  const {
    data: extractionData,
    isLoading: isExtLoading,
    isError: isExtError,
    error: extError,
    refetch: refetchExt,
  } = useQuery<ExtractionResponse>({
    queryKey: ['extraction', id],
    queryFn: async () => {
      const { data, error: apiErr, response } = await api.GET(
        '/documents/{document_id}/extraction',
        {
          params: { path: { document_id: id! } },
        }
      );
      if (apiErr || !data) {
        throw parseApiError(apiErr, response?.status);
      }
      return data;
    },
    enabled: !!id,
  });

  // Local Form State
  const [headersState, setHeadersState] = useState<HeaderFormState>({
    vendor_name: '',
    vendor_gstin: '',
    invoice_number: '',
    invoice_date: '',
    currency: 'INR',
    subtotal: '0.00',
    cgst: '0.00',
    sgst: '0.00',
    igst: '0.00',
    total: '0.00',
    note: '',
  });

  const [lineItemsState, setLineItemsState] = useState<LineItemFormState[]>([]);
  const [initialHeaders, setInitialHeaders] = useState<HeaderFormState | null>(null);
  const [initialLineItems, setInitialLineItems] = useState<LineItemFormState[] | null>(null);

  // Initialize form state when extraction data arrives
  useEffect(() => {
    if (extractionData) {
      const d = (extractionData.data || {}) as Record<string, unknown>;
      const initH: HeaderFormState = {
        vendor_name: String(d.vendor_name || ''),
        vendor_gstin: String(d.vendor_gstin || ''),
        invoice_number: String(d.invoice_number || ''),
        invoice_date: String(d.invoice_date || ''),
        currency: String(d.currency || 'INR'),
        subtotal: String(d.subtotal ?? '0.00'),
        cgst: String(d.cgst ?? '0.00'),
        sgst: String(d.sgst ?? '0.00'),
        igst: String(d.igst ?? '0.00'),
        total: String(d.total ?? '0.00'),
        note: '',
      };

      const initL: LineItemFormState[] = (extractionData.line_items || []).map((li) => ({
        id: li.id,
        description: li.description,
        quantity: String(li.quantity),
        unit_price: String(li.unit_price),
        amount: String(li.amount),
      }));

      setHeadersState(initH);
      setLineItemsState(initL);
      setInitialHeaders(initH);
      setInitialLineItems(initL);
    }
  }, [extractionData]);

  // Dirty state calculation
  const isDirty = useMemo(() => {
    if (!initialHeaders || !initialLineItems) return false;

    const headersDirty = Object.keys(headersState).some((k) => {
      const key = k as keyof HeaderFormState;
      if (key === 'note') return headersState.note.trim().length > 0;
      return headersState[key] !== initialHeaders[key];
    });

    if (headersDirty) return true;

    if (lineItemsState.length !== initialLineItems.length) return true;

    for (let i = 0; i < lineItemsState.length; i++) {
      const cur = lineItemsState[i];
      const orig = initialLineItems[i];
      if (
        cur.description !== orig.description ||
        cur.quantity !== orig.quantity ||
        cur.unit_price !== orig.unit_price ||
        cur.amount !== orig.amount
      ) {
        return true;
      }
    }

    return false;
  }, [headersState, lineItemsState, initialHeaders, initialLineItems]);

  // Browser tab close protection
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (isDirty) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [isDirty]);

  // Intercept in-app navigation when dirty
  const handleProtectedNavigate = (to: string) => {
    if (isDirty) {
      setPendingNavigateTo(to);
      setIsUnsavedLeaveModalOpen(true);
    } else {
      navigate(to);
    }
  };

  // Original model data lookup for human comparison
  const originalModelData = useMemo(() => {
    return (extractionData?.original_data || {}) as Record<string, unknown>;
  }, [extractionData]);

  // Read-only condition
  const isReadOnly =
    documentData?.status !== 'needs_review' || !isReviewerOrAdmin;

  // Validation issues mapping
  const issues = useMemo(
    () => extractionData?.validation_issues || [],
    [extractionData?.validation_issues]
  );
  const errorIssues = useMemo(() => issues.filter((i) => i.severity === 'error'), [issues]);

  // Input validation state map for outlines
  const issueFieldMap = useMemo(() => {
    const map: Record<string, { severity: 'error' | 'warning'; message: string }> = {};
    for (const issue of issues) {
      if (issue.field) {
        // Errors take precedence over warnings
        if (!map[issue.field] || issue.severity === 'error') {
          map[issue.field] = {
            severity: issue.severity as 'error' | 'warning',
            message: issue.message,
          };
        }
      }
    }
    return map;
  }, [issues]);

  // Client-side decimal validation error tracker
  const [decimalErrors, setDecimalErrors] = useState<Record<string, string>>({});

  const validateDecimals = (): boolean => {
    const errors: Record<string, string> = {};
    const moneyFields: (keyof HeaderFormState)[] = [
      'subtotal',
      'cgst',
      'sgst',
      'igst',
      'total',
    ];

    for (const f of moneyFields) {
      const val = headersState[f].trim();
      if (!DECIMAL_REGEX.test(val)) {
        errors[f] = 'Must be a valid decimal number (e.g. 100.50)';
      }
    }

    lineItemsState.forEach((item, index) => {
      if (!DECIMAL_REGEX.test(item.quantity.trim())) {
        errors[`line_items.${index}.quantity`] = 'Valid decimal required';
      }
      if (!DECIMAL_REGEX.test(item.unit_price.trim())) {
        errors[`line_items.${index}.unit_price`] = 'Valid decimal required';
      }
      if (!DECIMAL_REGEX.test(item.amount.trim())) {
        errors[`line_items.${index}.amount`] = 'Valid decimal required';
      }
    });

    setDecimalErrors(errors);
    return Object.keys(errors).length === 0;
  };

  // Focus and scroll to field on issue click
  const handleSelectField = (field: string) => {
    setActiveTab('details');
    const input = inputRefs.current[field];
    if (input) {
      input.scrollIntoView({ behavior: 'smooth', block: 'center' });
      input.focus();
    }
  };

  // 3. Save Mutation (PATCH /documents/{id}/extraction)
  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!extractionData) return;

      if (!validateDecimals()) {
        throw new Error('Please resolve decimal format errors before saving.');
      }

      // Compute changed header fields
      const patchBody: Record<string, unknown> = {
        version: extractionData.version,
      };

      if (initialHeaders) {
        if (headersState.vendor_name !== initialHeaders.vendor_name) {
          patchBody.vendor_name = headersState.vendor_name;
        }
        if (headersState.vendor_gstin !== initialHeaders.vendor_gstin) {
          patchBody.vendor_gstin = headersState.vendor_gstin || null;
        }
        if (headersState.invoice_number !== initialHeaders.invoice_number) {
          patchBody.invoice_number = headersState.invoice_number;
        }
        if (headersState.invoice_date !== initialHeaders.invoice_date) {
          patchBody.invoice_date = headersState.invoice_date || null;
        }
        if (headersState.currency !== initialHeaders.currency) {
          patchBody.currency = headersState.currency;
        }
        if (headersState.subtotal !== initialHeaders.subtotal) {
          patchBody.subtotal = headersState.subtotal;
        }
        if (headersState.cgst !== initialHeaders.cgst) {
          patchBody.cgst = headersState.cgst;
        }
        if (headersState.sgst !== initialHeaders.sgst) {
          patchBody.sgst = headersState.sgst;
        }
        if (headersState.igst !== initialHeaders.igst) {
          patchBody.igst = headersState.igst;
        }
        if (headersState.total !== initialHeaders.total) {
          patchBody.total = headersState.total;
        }
      }

      // Send line items full list if modified
      const isLineItemsModified =
        JSON.stringify(lineItemsState) !== JSON.stringify(initialLineItems);
      if (isLineItemsModified) {
        patchBody.line_items = lineItemsState.map((li) => ({
          description: li.description,
          quantity: li.quantity,
          unit_price: li.unit_price,
          amount: li.amount,
        }));
      }

      if (headersState.note.trim()) {
        patchBody.note = headersState.note.trim();
      }

      const { data, error: apiErr, response } = await api.PATCH(
        '/documents/{document_id}/extraction',
        {
          params: { path: { document_id: id! } },
          body: patchBody as unknown as paths['/documents/{document_id}/extraction']['patch']['requestBody']['content']['application/json'],
        }
      );

      if (response?.status === 409) {
        throw { isConflict: true };
      }

      if (apiErr || !data) {
        throw parseApiError(apiErr, response?.status);
      }

      return data;
    },
    onSuccess: (newExt) => {
      toast.success('Changes saved successfully. Validation issues re-evaluated.');
      queryClient.setQueryData(['extraction', id], newExt);
      queryClient.invalidateQueries({ queryKey: ['document', id] });
      queryClient.invalidateQueries({ queryKey: ['review-queue'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
    },
    onError: (err: unknown) => {
      if ((err as { isConflict?: boolean })?.isConflict) {
        setIsConflictOpen(true);
        return;
      }
      const parsed = parseApiError(err);
      toast.error(parsed.message || 'Failed to save changes.');
    },
  });

  // Keyboard shortcut Ctrl/Cmd+S to save
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        if (!isReadOnly && !saveMutation.isPending) {
          saveMutation.mutate();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isReadOnly, saveMutation]);

  // 4. Approve Mutation
  const approveMutation = useMutation({
    mutationFn: async ({ override, reason }: { override: boolean; reason?: string }) => {
      const { data, error: apiErr, response } = await api.POST(
        '/documents/{document_id}/approve',
        {
          params: { path: { document_id: id! } },
          body: { override, reason: reason || null },
        }
      );
      if (apiErr || !data) {
        throw parseApiError(apiErr, response?.status);
      }
      return data;
    },
    onSuccess: (updatedDoc) => {
      toast.success('Invoice approved successfully.');
      queryClient.setQueryData(['document', id], updatedDoc);
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['review-queue'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
      setIsApproveModalOpen(false);
      setOverrideReason('');
    },
    onError: (err: unknown) => {
      const parsed = parseApiError(err);
      toast.error(parsed.message || 'Failed to approve document.');
    },
  });

  const handleApproveClick = () => {
    if (isDirty) {
      toast.error('You have unsaved changes. Please save before approving.');
      return;
    }
    if (errorIssues.length > 0) {
      setIsApproveModalOpen(true);
    } else {
      approveMutation.mutate({ override: false });
    }
  };

  // 5. Reject Mutation
  const rejectMutation = useMutation({
    mutationFn: async (reason: string) => {
      const { data, error: apiErr, response } = await api.POST(
        '/documents/{document_id}/reject',
        {
          params: { path: { document_id: id! } },
          body: { reason },
        }
      );
      if (apiErr || !data) {
        throw parseApiError(apiErr, response?.status);
      }
      return data;
    },
    onSuccess: (updatedDoc) => {
      toast.success('Invoice rejected.');
      queryClient.setQueryData(['document', id], updatedDoc);
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['review-queue'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
      setIsRejectModalOpen(false);
      setRejectReason('');
    },
    onError: (err: unknown) => {
      const parsed = parseApiError(err);
      toast.error(parsed.message || 'Failed to reject document.');
    },
  });

  // 6. Reopen Mutation (Admin only)
  const reopenMutation = useMutation({
    mutationFn: async () => {
      const { data, error: apiErr, response } = await api.POST(
        '/documents/{document_id}/reopen',
        {
          params: { path: { document_id: id! } },
        }
      );
      if (apiErr || !data) {
        throw parseApiError(apiErr, response?.status);
      }
      return data;
    },
    onSuccess: (updatedDoc) => {
      toast.success('Invoice reopened into needs_review status.');
      queryClient.setQueryData(['document', id], updatedDoc);
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['review-queue'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
      setIsReopenModalOpen(false);
    },
    onError: (err: unknown) => {
      const parsed = parseApiError(err);
      toast.error(parsed.message || 'Failed to reopen document.');
    },
  });

  // Line items handlers
  const handleAddLineItem = () => {
    setLineItemsState((prev) => [
      ...prev,
      {
        description: '',
        quantity: '1.00',
        unit_price: '0.00',
        amount: '0.00',
      },
    ]);
  };

  const handleRemoveLineItem = (index: number) => {
    setLineItemsState((prev) => prev.filter((_, i) => i !== index));
  };

  const handleUpdateLineItem = (
    index: number,
    field: keyof LineItemFormState,
    value: string
  ) => {
    setLineItemsState((prev) => {
      const copy = [...prev];
      copy[index] = { ...copy[index], [field]: value };
      return copy;
    });
  };

  if (isDocLoading || isExtLoading) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-16 text-center shadow-sm">
        <RefreshCw className="w-8 h-8 animate-spin text-sky-600 mx-auto mb-3" />
        <p className="text-sm font-medium text-gray-700">Loading invoice review workspace...</p>
      </div>
    );
  }

  if (isDocError || isExtError || !documentData) {
    const errorMsg =
      (docError as { message?: string })?.message ||
      (extError as { message?: string })?.message ||
      'Document not found or inaccessible.';

    return (
      <div className="bg-white rounded-xl border border-rose-200 p-8 text-center shadow-sm max-w-lg mx-auto">
        <AlertCircle className="w-8 h-8 text-rose-500 mx-auto mb-2" />
        <h3 className="text-base font-semibold text-gray-900">Failed to load invoice</h3>
        <p className="text-xs text-rose-600 mt-1">{errorMsg}</p>
        <div className="mt-4 flex justify-center gap-3">
          <Button variant="outline" size="sm" onClick={() => navigate('/documents')}>
            Back to Documents
          </Button>
          <Button
            size="sm"
            onClick={() => {
              refetchDoc();
              refetchExt();
            }}
          >
            Retry
          </Button>
        </div>
      </div>
    );
  }

  const canReopen =
    role === 'admin' &&
    (documentData.status === 'approved' || documentData.status === 'rejected') &&
    !documentData.export_batch_id;

  return (
    <div className="space-y-4">
      {/* Top Breadcrumb & Status Summary Bar */}
      <div className="bg-white border border-gray-200/80 rounded-xl p-4 shadow-sm space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="flex items-center gap-3">
            <button
              onClick={() => handleProtectedNavigate('/documents')}
              className="p-1 text-gray-400 hover:text-gray-700 rounded-lg hover:bg-gray-100 transition-colors"
              aria-label="Back to documents"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h1
                  className="text-lg font-bold text-gray-900 truncate max-w-sm"
                  title={documentData.original_filename}
                >
                  {documentData.original_filename}
                </h1>
                <StatusBadge status={documentData.status} />
                <span className="text-xs bg-gray-100 text-gray-600 font-mono px-2 py-0.5 rounded border border-gray-200">
                  v{extractionData?.version ?? 1}
                </span>
                {isDirty && (
                  <span
                    className="text-xs bg-amber-100 text-amber-800 font-medium px-2 py-0.5 rounded border border-amber-300"
                    data-testid="dirty-indicator"
                  >
                    Unsaved edits
                  </span>
                )}
              </div>
              <div className="text-xs text-gray-400 flex items-center gap-2 mt-0.5">
                <span>Uploaded: {new Date(documentData.created_at).toLocaleDateString()}</span>
                <span>•</span>
                <span>Model: {extractionData?.model || 'mock-model'}</span>
              </div>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-2 flex-wrap self-end sm:self-auto">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setIsHistoryOpen(true)}
              className="gap-1.5"
              aria-label="Open document audit history"
            >
              <History className="w-4 h-4 text-gray-500" />
              <span>History</span>
            </Button>

            {canReopen && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setIsReopenModalOpen(true)}
                className="gap-1.5 text-amber-700 hover:bg-amber-50 border-amber-200"
                data-testid="reopen-btn"
              >
                <RotateCcw className="w-4 h-4" />
                <span>Reopen</span>
              </Button>
            )}

            {!isReadOnly && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setIsRejectModalOpen(true)}
                  className="gap-1.5 text-rose-700 hover:bg-rose-50 border-rose-200"
                  data-testid="reject-btn"
                >
                  <XCircle className="w-4 h-4" />
                  <span>Reject</span>
                </Button>

                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => saveMutation.mutate()}
                  disabled={saveMutation.isPending || !isDirty}
                  isLoading={saveMutation.isPending}
                  className="gap-1.5"
                  title="Save changes (Ctrl+S)"
                  data-testid="save-extraction-btn"
                >
                  <Save className="w-4 h-4" />
                  <span>Save (Ctrl+S)</span>
                </Button>

                <Button
                  size="sm"
                  onClick={handleApproveClick}
                  disabled={approveMutation.isPending || isDirty}
                  isLoading={approveMutation.isPending}
                  className="gap-1.5 bg-emerald-600 hover:bg-emerald-700 focus:ring-emerald-500 text-white"
                  title={
                    isDirty
                      ? 'Save your changes before approving'
                      : errorIssues.length > 0
                        ? 'Requires override reason'
                        : 'Approve invoice'
                  }
                  data-testid="approve-btn"
                >
                  <CheckCircle2 className="w-4 h-4" />
                  <span>Approve</span>
                </Button>
              </>
            )}
          </div>
        </div>

        {/* Reviewed details if present */}
        {(documentData.reviewed_by || documentData.review_note) && (
          <div className="p-2.5 bg-gray-50 border border-gray-200 rounded-lg text-xs text-gray-600 flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5 text-gray-500" />
              <span>
                Reviewed by user <span className="font-mono">{documentData.reviewed_by?.slice(0, 8)}…</span>
                {documentData.reviewed_at && (
                  <> on {new Date(documentData.reviewed_at).toLocaleString()}</>
                )}
              </span>
            </div>
            {documentData.review_note && (
              <span className="italic text-gray-700 bg-white px-2 py-0.5 rounded border border-gray-200">
                Note: {documentData.review_note}
              </span>
            )}
          </div>
        )}

        {/* Small Screen Tab Switcher */}
        <div className="flex lg:hidden border-b border-gray-200 pt-2 gap-2">
          <button
            onClick={() => setActiveTab('preview')}
            className={`pb-2 text-xs font-semibold px-3 border-b-2 transition-colors ${
              activeTab === 'preview'
                ? 'border-sky-600 text-sky-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            Invoice Preview
          </button>
          <button
            onClick={() => setActiveTab('details')}
            className={`pb-2 text-xs font-semibold px-3 border-b-2 transition-colors ${
              activeTab === 'details'
                ? 'border-sky-600 text-sky-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            Extraction &amp; Review ({issues.length} issues)
          </button>
        </div>
      </div>

      {/* Main Split Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* LEFT COLUMN: Original Document File (PDF / Image) */}
        <div
          className={`lg:col-span-5 h-[calc(100vh-210px)] sticky top-20 ${
            activeTab === 'preview' ? 'block' : 'hidden lg:block'
          }`}
        >
          <DocumentViewer
            documentId={documentData.id}
            contentType={documentData.content_type}
            filename={documentData.original_filename}
          />
        </div>

        {/* RIGHT COLUMN: Issues Panel + Editable Extraction Data */}
        <div
          className={`lg:col-span-7 space-y-6 ${
            activeTab === 'details' ? 'block' : 'hidden lg:block'
          }`}
        >
          {/* Validation Issues Panel */}
          <IssuesPanel issues={issues} onSelectField={handleSelectField} />

          {/* Read-Only Notice when not editable */}
          {isReadOnly && (
            <div className="p-3 bg-gray-100 border border-gray-200 rounded-xl text-xs text-gray-600 flex items-center gap-2">
              <FileText className="w-4 h-4 text-gray-500 shrink-0" />
              <span>
                {documentData.status !== 'needs_review'
                  ? `This invoice is in '${documentData.status}' status and cannot be edited.`
                  : 'You are signed in as Viewer (read-only access).'}
              </span>
            </div>
          )}

          {/* Extraction Header Form */}
          <div className="bg-white border border-gray-200/80 rounded-xl p-6 shadow-sm space-y-6">
            <h3 className="text-base font-semibold text-gray-900 border-b border-gray-100 pb-3">
              Invoice Header Information
            </h3>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {/* Vendor Name */}
              <div>
                <Input
                  label="Vendor Name"
                  id="input-vendor_name"
                  ref={(el) => {
                    inputRefs.current['vendor_name'] = el;
                  }}
                  value={headersState.vendor_name}
                  disabled={isReadOnly}
                  onChange={(e) =>
                    setHeadersState((prev) => ({ ...prev, vendor_name: e.target.value }))
                  }
                  error={
                    issueFieldMap['vendor_name']?.severity === 'error'
                      ? issueFieldMap['vendor_name'].message
                      : undefined
                  }
                  warning={
                    issueFieldMap['vendor_name']?.severity === 'warning'
                      ? issueFieldMap['vendor_name'].message
                      : undefined
                  }
                  placeholder="Acme Supplier Inc"
                />
                {originalModelData.vendor_name !== undefined &&
                  String(originalModelData.vendor_name) !== headersState.vendor_name && (
                    <p className="mt-1 text-[11px] text-gray-500 font-mono">
                      Original model value:{' '}
                      <span className="font-semibold">{String(originalModelData.vendor_name)}</span>
                    </p>
                  )}
              </div>

              {/* Vendor GSTIN */}
              <div>
                <Input
                  label="Vendor GSTIN"
                  id="input-vendor_gstin"
                  ref={(el) => {
                    inputRefs.current['vendor_gstin'] = el;
                  }}
                  value={headersState.vendor_gstin}
                  disabled={isReadOnly}
                  onChange={(e) =>
                    setHeadersState((prev) => ({ ...prev, vendor_gstin: e.target.value }))
                  }
                  error={
                    issueFieldMap['vendor_gstin']?.severity === 'error'
                      ? issueFieldMap['vendor_gstin'].message
                      : undefined
                  }
                  warning={
                    issueFieldMap['vendor_gstin']?.severity === 'warning'
                      ? issueFieldMap['vendor_gstin'].message
                      : undefined
                  }
                  placeholder="27AABCU9603R1ZM"
                />
                {originalModelData.vendor_gstin !== undefined &&
                  String(originalModelData.vendor_gstin || '') !== headersState.vendor_gstin && (
                    <p className="mt-1 text-[11px] text-gray-500 font-mono">
                      Original model value:{' '}
                      <span className="font-semibold">
                        {String(originalModelData.vendor_gstin || 'none')}
                      </span>
                    </p>
                  )}
              </div>

              {/* Invoice Number */}
              <div>
                <Input
                  label="Invoice Number"
                  id="input-invoice_number"
                  ref={(el) => {
                    inputRefs.current['invoice_number'] = el;
                  }}
                  value={headersState.invoice_number}
                  disabled={isReadOnly}
                  onChange={(e) =>
                    setHeadersState((prev) => ({ ...prev, invoice_number: e.target.value }))
                  }
                  error={
                    issueFieldMap['invoice_number']?.severity === 'error'
                      ? issueFieldMap['invoice_number'].message
                      : undefined
                  }
                  warning={
                    issueFieldMap['invoice_number']?.severity === 'warning'
                      ? issueFieldMap['invoice_number'].message
                      : undefined
                  }
                  placeholder="INV-2026-001"
                />
                {originalModelData.invoice_number !== undefined &&
                  String(originalModelData.invoice_number) !== headersState.invoice_number && (
                    <p className="mt-1 text-[11px] text-gray-500 font-mono">
                      Original model value:{' '}
                      <span className="font-semibold">{String(originalModelData.invoice_number)}</span>
                    </p>
                  )}
              </div>

              {/* Invoice Date */}
              <div>
                <Input
                  label="Invoice Date"
                  id="input-invoice_date"
                  type="date"
                  ref={(el) => {
                    inputRefs.current['invoice_date'] = el;
                  }}
                  value={headersState.invoice_date}
                  disabled={isReadOnly}
                  onChange={(e) =>
                    setHeadersState((prev) => ({ ...prev, invoice_date: e.target.value }))
                  }
                  error={
                    issueFieldMap['invoice_date']?.severity === 'error'
                      ? issueFieldMap['invoice_date'].message
                      : undefined
                  }
                  warning={
                    issueFieldMap['invoice_date']?.severity === 'warning'
                      ? issueFieldMap['invoice_date'].message
                      : undefined
                  }
                />
                {originalModelData.invoice_date !== undefined &&
                  String(originalModelData.invoice_date) !== headersState.invoice_date && (
                    <p className="mt-1 text-[11px] text-gray-500 font-mono">
                      Original model value:{' '}
                      <span className="font-semibold">{String(originalModelData.invoice_date)}</span>
                    </p>
                  )}
              </div>

              {/* Currency */}
              <div>
                <Input
                  label="Currency"
                  id="input-currency"
                  ref={(el) => {
                    inputRefs.current['currency'] = el;
                  }}
                  value={headersState.currency}
                  disabled={isReadOnly}
                  onChange={(e) =>
                    setHeadersState((prev) => ({ ...prev, currency: e.target.value }))
                  }
                  placeholder="INR"
                />
              </div>

              {/* Subtotal */}
              <div>
                <Input
                  label="Subtotal"
                  id="input-subtotal"
                  ref={(el) => {
                    inputRefs.current['subtotal'] = el;
                  }}
                  value={headersState.subtotal}
                  disabled={isReadOnly}
                  onChange={(e) =>
                    setHeadersState((prev) => ({ ...prev, subtotal: e.target.value }))
                  }
                  error={
                    decimalErrors['subtotal'] ||
                    (issueFieldMap['subtotal']?.severity === 'error'
                      ? issueFieldMap['subtotal'].message
                      : undefined)
                  }
                  warning={
                    issueFieldMap['subtotal']?.severity === 'warning'
                      ? issueFieldMap['subtotal'].message
                      : undefined
                  }
                />
                {originalModelData.subtotal !== undefined &&
                  String(originalModelData.subtotal) !== headersState.subtotal && (
                    <p className="mt-1 text-[11px] text-gray-500 font-mono">
                      Original model value:{' '}
                      <span className="font-semibold">{String(originalModelData.subtotal)}</span>
                    </p>
                  )}
              </div>

              {/* CGST */}
              <div>
                <Input
                  label="CGST"
                  id="input-cgst"
                  ref={(el) => {
                    inputRefs.current['cgst'] = el;
                  }}
                  value={headersState.cgst}
                  disabled={isReadOnly}
                  onChange={(e) =>
                    setHeadersState((prev) => ({ ...prev, cgst: e.target.value }))
                  }
                  error={
                    decimalErrors['cgst'] ||
                    (issueFieldMap['cgst']?.severity === 'error'
                      ? issueFieldMap['cgst'].message
                      : undefined)
                  }
                  warning={
                    issueFieldMap['cgst']?.severity === 'warning'
                      ? issueFieldMap['cgst'].message
                      : undefined
                  }
                />
              </div>

              {/* SGST */}
              <div>
                <Input
                  label="SGST"
                  id="input-sgst"
                  ref={(el) => {
                    inputRefs.current['sgst'] = el;
                  }}
                  value={headersState.sgst}
                  disabled={isReadOnly}
                  onChange={(e) =>
                    setHeadersState((prev) => ({ ...prev, sgst: e.target.value }))
                  }
                  error={
                    decimalErrors['sgst'] ||
                    (issueFieldMap['sgst']?.severity === 'error'
                      ? issueFieldMap['sgst'].message
                      : undefined)
                  }
                  warning={
                    issueFieldMap['sgst']?.severity === 'warning'
                      ? issueFieldMap['sgst'].message
                      : undefined
                  }
                />
              </div>

              {/* IGST */}
              <div>
                <Input
                  label="IGST"
                  id="input-igst"
                  ref={(el) => {
                    inputRefs.current['igst'] = el;
                  }}
                  value={headersState.igst}
                  disabled={isReadOnly}
                  onChange={(e) =>
                    setHeadersState((prev) => ({ ...prev, igst: e.target.value }))
                  }
                  error={
                    decimalErrors['igst'] ||
                    (issueFieldMap['igst']?.severity === 'error'
                      ? issueFieldMap['igst'].message
                      : undefined)
                  }
                  warning={
                    issueFieldMap['igst']?.severity === 'warning'
                      ? issueFieldMap['igst'].message
                      : undefined
                  }
                />
              </div>

              {/* Total */}
              <div>
                <Input
                  label="Total Amount"
                  id="input-total"
                  ref={(el) => {
                    inputRefs.current['total'] = el;
                  }}
                  value={headersState.total}
                  disabled={isReadOnly}
                  onChange={(e) =>
                    setHeadersState((prev) => ({ ...prev, total: e.target.value }))
                  }
                  error={
                    decimalErrors['total'] ||
                    (issueFieldMap['total']?.severity === 'error'
                      ? issueFieldMap['total'].message
                      : undefined)
                  }
                  warning={
                    issueFieldMap['total']?.severity === 'warning'
                      ? issueFieldMap['total'].message
                      : undefined
                  }
                />
                {originalModelData.total !== undefined &&
                  String(originalModelData.total) !== headersState.total && (
                    <p className="mt-1 text-[11px] text-gray-500 font-mono">
                      Original model value:{' '}
                      <span className="font-semibold">{String(originalModelData.total)}</span>
                    </p>
                  )}
              </div>
            </div>

            {/* Optional Edit Note */}
            {!isReadOnly && (
              <div className="pt-2">
                <Input
                  label="Review Note (Optional audit description)"
                  id="input-note"
                  value={headersState.note}
                  onChange={(e) =>
                    setHeadersState((prev) => ({ ...prev, note: e.target.value }))
                  }
                  placeholder="e.g. Corrected invoice total per paper tax invoice discrepancy"
                />
              </div>
            )}
          </div>

          {/* Editable Line Items Table */}
          <div className="bg-white border border-gray-200/80 rounded-xl p-6 shadow-sm space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-base font-semibold text-gray-900">Line Items</h3>
                <p className="text-xs text-gray-500">
                  Itemized quantities and unit prices (amounts remain exact string decimals)
                </p>
              </div>

              {!isReadOnly && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleAddLineItem}
                  className="gap-1"
                >
                  <Plus className="w-4 h-4" />
                  <span>Add Line Item</span>
                </Button>
              )}
            </div>

            {lineItemsState.length === 0 ? (
              <div className="p-8 text-center bg-gray-50 rounded-xl border border-dashed border-gray-300">
                <p className="text-sm text-gray-500">No line items extracted.</p>
                {!isReadOnly && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleAddLineItem}
                    className="mt-2"
                  >
                    Add First Line Item
                  </Button>
                )}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 text-left text-xs">
                  <thead className="bg-gray-50 text-gray-500 uppercase tracking-wider font-semibold">
                    <tr>
                      <th className="px-3 py-2.5">Description</th>
                      <th className="px-3 py-2.5 w-24">Qty</th>
                      <th className="px-3 py-2.5 w-28">Unit Price</th>
                      <th className="px-3 py-2.5 w-28">Amount</th>
                      {!isReadOnly && <th className="px-3 py-2.5 text-right w-12">Action</th>}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {lineItemsState.map((item, index) => (
                      <tr key={index} className="hover:bg-gray-50/60">
                        {/* Description */}
                        <td className="px-3 py-2">
                          <input
                            type="text"
                            value={item.description}
                            disabled={isReadOnly}
                            onChange={(e) =>
                              handleUpdateLineItem(index, 'description', e.target.value)
                            }
                            className="w-full px-2 py-1 rounded border border-gray-300 text-xs focus:ring-sky-500 focus:border-sky-500 bg-white disabled:bg-gray-50"
                            placeholder="Item description"
                            required
                          />
                        </td>

                        {/* Quantity */}
                        <td className="px-3 py-2">
                          <input
                            type="text"
                            value={item.quantity}
                            disabled={isReadOnly}
                            onChange={(e) =>
                              handleUpdateLineItem(index, 'quantity', e.target.value)
                            }
                            className={`w-full px-2 py-1 rounded border text-xs focus:ring-sky-500 focus:border-sky-500 bg-white disabled:bg-gray-50 ${
                              decimalErrors[`line_items.${index}.quantity`]
                                ? 'border-rose-500 bg-rose-50'
                                : 'border-gray-300'
                            }`}
                            placeholder="1.00"
                            required
                          />
                        </td>

                        {/* Unit Price */}
                        <td className="px-3 py-2">
                          <input
                            type="text"
                            value={item.unit_price}
                            disabled={isReadOnly}
                            onChange={(e) =>
                              handleUpdateLineItem(index, 'unit_price', e.target.value)
                            }
                            className={`w-full px-2 py-1 rounded border text-xs focus:ring-sky-500 focus:border-sky-500 bg-white disabled:bg-gray-50 ${
                              decimalErrors[`line_items.${index}.unit_price`]
                                ? 'border-rose-500 bg-rose-50'
                                : 'border-gray-300'
                            }`}
                            placeholder="100.00"
                            required
                          />
                        </td>

                        {/* Amount */}
                        <td className="px-3 py-2">
                          <input
                            type="text"
                            value={item.amount}
                            disabled={isReadOnly}
                            onChange={(e) =>
                              handleUpdateLineItem(index, 'amount', e.target.value)
                            }
                            className={`w-full px-2 py-1 rounded border text-xs focus:ring-sky-500 focus:border-sky-500 bg-white disabled:bg-gray-50 ${
                              decimalErrors[`line_items.${index}.amount`]
                                ? 'border-rose-500 bg-rose-50'
                                : 'border-gray-300'
                            }`}
                            placeholder="100.00"
                            required
                          />
                        </td>

                        {/* Delete action */}
                        {!isReadOnly && (
                          <td className="px-3 py-2 text-right">
                            <button
                              type="button"
                              onClick={() => handleRemoveLineItem(index)}
                              className="p-1 text-gray-400 hover:text-rose-600 rounded transition-colors"
                              title="Delete row"
                              aria-label={`Delete line item ${index + 1}`}
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* History Drawer Modal */}
      <HistoryDrawer
        documentId={documentData.id}
        isOpen={isHistoryOpen}
        onClose={() => setIsHistoryOpen(false)}
      />

      {/* 409 Conflict Modal */}
      <ConflictModal
        isOpen={isConflictOpen}
        onClose={() => setIsConflictOpen(false)}
        onConfirmReload={() => {
          setIsConflictOpen(false);
          refetchExt();
          refetchDoc();
        }}
        unsavedEditsSummary={
          initialHeaders
            ? (Object.fromEntries(
                Object.entries(headersState).filter(
                  ([k, v]) => v !== initialHeaders[k as keyof HeaderFormState]
                )
              ) as Record<string, string>)
            : {}
        }
      />

      {/* Approve with Overrides Modal */}
      <Modal
        isOpen={isApproveModalOpen}
        onClose={() => setIsApproveModalOpen(false)}
        title="Approve Invoice with Errors"
        maxWidth="md"
        footer={
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              onClick={() => setIsApproveModalOpen(false)}
              disabled={approveMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={() =>
                approveMutation.mutate({
                  override: true,
                  reason: overrideReason,
                })
              }
              disabled={!overrideReason.trim() || approveMutation.isPending}
              isLoading={approveMutation.isPending}
              className="bg-emerald-600 hover:bg-emerald-700"
              data-testid="confirm-approve-override-btn"
            >
              Confirm Override &amp; Approve
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-900 space-y-1">
            <p className="font-semibold">Unresolved Error Issues Exist:</p>
            <ul className="list-disc list-inside space-y-0.5 text-amber-800">
              {errorIssues.map((e) => (
                <li key={e.id}>
                  {e.code}: {e.message}
                </li>
              ))}
            </ul>
          </div>

          <p className="text-xs text-gray-600">
            To approve this invoice despite the mathematical or structural error(s), you must provide
            an audit reason for the override.
          </p>

          <Input
            label="Override Reason"
            id="input-override-reason"
            required
            value={overrideReason}
            onChange={(e) => setOverrideReason(e.target.value)}
            placeholder="e.g. Total discrepancy of 0.40 accepted as vendor roundoff discrepancy"
          />
        </div>
      </Modal>

      {/* Reject Modal */}
      <Modal
        isOpen={isRejectModalOpen}
        onClose={() => setIsRejectModalOpen(false)}
        title="Reject Invoice"
        maxWidth="md"
        footer={
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              onClick={() => setIsRejectModalOpen(false)}
              disabled={rejectMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={() => rejectMutation.mutate(rejectReason)}
              disabled={!rejectReason.trim() || rejectMutation.isPending}
              isLoading={rejectMutation.isPending}
              data-testid="confirm-reject-btn"
            >
              Confirm Rejection
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          <p className="text-xs text-gray-600">
            Rejecting this invoice marks it as rejected and removes it from the active review queue.
            A mandatory reason is required for compliance audit trails.
          </p>

          <Input
            label="Rejection Reason"
            id="input-reject-reason"
            required
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            placeholder="e.g. Duplicate billing against PO-99824; vendor billed twice"
          />
        </div>
      </Modal>

      {/* Reopen Modal */}
      <Modal
        isOpen={isReopenModalOpen}
        onClose={() => setIsReopenModalOpen(false)}
        title="Reopen Invoice to Review"
        maxWidth="md"
        footer={
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              onClick={() => setIsReopenModalOpen(false)}
              disabled={reopenMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              onClick={() => reopenMutation.mutate()}
              isLoading={reopenMutation.isPending}
              className="bg-amber-600 hover:bg-amber-700 text-white"
              data-testid="confirm-reopen-btn"
            >
              Reopen Document
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-xs text-gray-600">
          <p>
            Are you sure you want to reopen this document? It will return to{' '}
            <strong className="text-amber-800">needs_review</strong> status and become eligible for
            further corrections and review actions.
          </p>
          <p className="text-gray-500">
            Note: Once an invoice is included in a finalized export batch, it cannot be reopened.
          </p>
        </div>
      </Modal>

      {/* Unsaved Leave Confirmation Modal */}
      <Modal
        isOpen={isUnsavedLeaveModalOpen}
        onClose={() => setIsUnsavedLeaveModalOpen(false)}
        title="Unsaved Changes"
        maxWidth="sm"
        footer={
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              onClick={() => setIsUnsavedLeaveModalOpen(false)}
            >
              Stay on Page
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                setIsUnsavedLeaveModalOpen(false);
                if (pendingNavigateTo) {
                  navigate(pendingNavigateTo);
                }
              }}
            >
              Discard &amp; Leave
            </Button>
          </div>
        }
      >
        <p className="text-xs text-gray-600">
          You have unsaved changes on this invoice. If you leave now, your pending edits will be
          lost.
        </p>
      </Modal>
    </div>
  );
};
