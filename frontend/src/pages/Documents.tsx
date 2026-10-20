import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { parseApiError } from '../api/errors';
import { useAuth } from '../auth/useAuth';
import { StatusBadge } from '../components/common/StatusBadge';
import { Button } from '../components/common/Button';
import { UploadModal } from '../components/documents/UploadModal';
import { useToast } from '../components/common/useToast';
import {
  Upload,
  RefreshCw,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Filter,
  FileText,
  AlertTriangle,
  RotateCcw,
} from 'lucide-react';

const PAGE_SIZE = 10;

export const Documents: React.FC = () => {
  const { role } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();

  const [page, setPage] = useState(0);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [hasIssuesFilter, setHasIssuesFilter] = useState<string>('');
  const [isUploadOpen, setIsUploadOpen] = useState(false);

  const canUploadOrReprocess = role === 'admin' || role === 'reviewer';

  const queryParams = {
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    ...(statusFilter ? { status: statusFilter } : {}),
    ...(hasIssuesFilter === 'true'
      ? { has_issues: true }
      : hasIssuesFilter === 'false'
        ? { has_issues: false }
        : {}),
  };

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['documents', queryParams],
    queryFn: async () => {
      const { data: resData, error: apiErr, response } = await api.GET('/documents', {
        params: { query: queryParams },
      });

      if (apiErr || !resData) {
        throw parseApiError(apiErr, response?.status);
      }
      return resData;
    },
    // Poll every 2s ONLY while any visible document is uploaded or processing
    refetchInterval: (query) => {
      const items = query.state.data?.items;
      if (!items || items.length === 0) return false;
      const hasActive = items.some(
        (doc) => doc.status === 'uploaded' || doc.status === 'processing'
      );
      return hasActive ? 2000 : false;
    },
  });

  // Reprocess mutation for failed documents
  const reprocessMutation = useMutation({
    mutationFn: async (documentId: string) => {
      const { data: resData, error: apiErr, response } = await api.POST(
        '/documents/{document_id}/reprocess',
        {
          params: { path: { document_id: documentId } },
        }
      );
      if (apiErr || !resData) {
        throw parseApiError(apiErr, response?.status);
      }
      return resData;
    },
    onSuccess: (updatedDoc) => {
      toast.success(`Reprocessing started for invoice`);
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
      queryClient.setQueryData(['documents', queryParams], (old: typeof data) => {
        if (!old) return old;
        return {
          ...old,
          items: old.items.map((item) => (item.id === updatedDoc.id ? updatedDoc : item)),
        };
      });
    },
    onError: (err: unknown) => {
      const parsed = parseApiError(err);
      toast.error(parsed.message || 'Failed to reprocess document');
    },
  });

  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);
  const items = data?.items ?? [];

  const handleFilterChange = (newStatus: string, newHasIssues: string) => {
    setStatusFilter(newStatus);
    setHasIssuesFilter(newHasIssues);
    setPage(0);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Documents</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage and view all incoming invoices and their extraction statuses
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
            className="gap-1.5"
            aria-label="Refresh documents list"
          >
            <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </Button>

          {canUploadOrReprocess && (
            <Button
              size="sm"
              onClick={() => setIsUploadOpen(true)}
              className="gap-1.5"
              data-testid="open-upload-btn"
            >
              <Upload className="w-4 h-4" />
              <span>Upload Invoice</span>
            </Button>
          )}
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white p-4 rounded-xl border border-gray-200 shadow-sm flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2 text-sm text-gray-600 font-medium">
          <Filter className="w-4 h-4 text-gray-400" />
          <span>Filters:</span>
        </div>

        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="filter-status" className="text-xs text-gray-500 font-medium">
            Status:
          </label>
          <select
            id="filter-status"
            value={statusFilter}
            onChange={(e) => handleFilterChange(e.target.value, hasIssuesFilter)}
            className="rounded-lg border border-gray-300 py-1.5 px-2.5 text-xs focus:ring-sky-500 focus:border-sky-500 bg-white"
          >
            <option value="">All Statuses</option>
            <option value="uploaded">Uploaded</option>
            <option value="processing">Processing</option>
            <option value="extracted">Extracted</option>
            <option value="needs_review">Needs Review</option>
            <option value="auto_approved">Auto Approved</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="failed">Failed</option>
            <option value="exported">Exported</option>
          </select>
        </div>

        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="filter-issues" className="text-xs text-gray-500 font-medium">
            Issues:
          </label>
          <select
            id="filter-issues"
            value={hasIssuesFilter}
            onChange={(e) => handleFilterChange(statusFilter, e.target.value)}
            className="rounded-lg border border-gray-300 py-1.5 px-2.5 text-xs focus:ring-sky-500 focus:border-sky-500 bg-white"
          >
            <option value="">All Documents</option>
            <option value="true">With Issues</option>
            <option value="false">Without Issues</option>
          </select>
        </div>

        {(statusFilter || hasIssuesFilter) && (
          <button
            onClick={() => handleFilterChange('', '')}
            className="text-xs text-sky-600 hover:text-sky-800 font-medium ml-auto"
          >
            Clear Filters
          </button>
        )}
      </div>

      {/* Main Content Area */}
      {isLoading ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center shadow-sm">
          <RefreshCw className="w-8 h-8 animate-spin text-sky-600 mx-auto mb-3" />
          <p className="text-sm font-medium text-gray-600">Loading documents...</p>
        </div>
      ) : isError ? (
        <div className="bg-white rounded-xl border border-rose-200 p-8 text-center shadow-sm">
          <AlertCircle className="w-8 h-8 text-rose-500 mx-auto mb-2" />
          <h3 className="text-base font-semibold text-gray-900">Failed to load documents</h3>
          <p className="text-xs text-gray-500 mt-1 max-w-md mx-auto">
            {(error as { message?: string })?.message || 'An unexpected network error occurred.'}
          </p>
          <Button variant="outline" size="sm" onClick={() => refetch()} className="mt-4">
            Try Again
          </Button>
        </div>
      ) : items.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center shadow-sm">
          <FileText className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <h3 className="text-base font-semibold text-gray-900">No documents found</h3>
          <p className="text-xs text-gray-500 mt-1 max-w-sm mx-auto">
            {statusFilter || hasIssuesFilter
              ? 'No documents match the current filter criteria.'
              : 'Get started by uploading your first invoice for processing.'}
          </p>
          {canUploadOrReprocess && !statusFilter && !hasIssuesFilter && (
            <Button
              size="sm"
              onClick={() => setIsUploadOpen(true)}
              className="mt-4 gap-1.5"
            >
              <Upload className="w-4 h-4" />
              <span>Upload Invoice</span>
            </Button>
          )}
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-left text-sm">
              <thead className="bg-gray-50/75 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                <tr>
                  <th scope="col" className="px-6 py-3.5">
                    Status
                  </th>
                  <th scope="col" className="px-6 py-3.5">
                    Filename
                  </th>
                  <th scope="col" className="px-6 py-3.5">
                    Uploaded
                  </th>
                  <th scope="col" className="px-6 py-3.5">
                    Issues / Reason
                  </th>
                  <th scope="col" className="px-6 py-3.5 text-right">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {items.map((doc) => {
                  const isProcessing =
                    doc.status === 'uploaded' || doc.status === 'processing';

                  return (
                    <tr
                      key={doc.id}
                      className="hover:bg-gray-50/60 transition-colors"
                      data-testid={`document-row-${doc.id}`}
                    >
                      {/* Status */}
                      <td className="px-6 py-4 whitespace-nowrap">
                        <StatusBadge status={doc.status} />
                      </td>

                      {/* Filename (Untrusted Plain Text) */}
                      <td className="px-6 py-4 whitespace-nowrap max-w-xs truncate">
                        <Link
                          to={`/documents/${doc.id}`}
                          className="font-medium text-gray-900 hover:text-sky-600 transition-colors block truncate"
                          title={doc.original_filename}
                          data-testid="document-filename"
                        >
                          {doc.original_filename}
                        </Link>
                        <span className="text-xs text-gray-400">
                          {(doc.size_bytes / 1024).toFixed(0)} KB
                        </span>
                      </td>

                      {/* Upload Date */}
                      <td className="px-6 py-4 whitespace-nowrap text-xs text-gray-500">
                        {new Date(doc.created_at).toLocaleDateString(undefined, {
                          year: 'numeric',
                          month: 'short',
                          day: 'numeric',
                        })}
                      </td>

                      {/* Issues / Reason / Error */}
                      <td className="px-6 py-4 text-xs">
                        {doc.status === 'failed' ? (
                          <div className="flex items-start gap-1.5 text-rose-700 max-w-md">
                            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-rose-500" />
                            <span className="truncate block" title={doc.error_message || 'Processing failed'}>
                              {doc.error_message || 'Processing failed'}
                            </span>
                          </div>
                        ) : doc.review_reason ? (
                          <div className="flex items-start gap-1.5 text-amber-800 max-w-md">
                            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5 text-amber-500" />
                            <span className="truncate block" title={doc.review_reason}>
                              {doc.review_reason}
                            </span>
                          </div>
                        ) : isProcessing ? (
                          <span className="text-gray-400 italic">Processing extraction...</span>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="px-6 py-4 whitespace-nowrap text-right text-xs font-medium space-x-2">
                        {doc.status === 'failed' && canUploadOrReprocess && (
                          <button
                            onClick={() => reprocessMutation.mutate(doc.id)}
                            disabled={reprocessMutation.isPending}
                            className="inline-flex items-center gap-1 text-rose-600 hover:text-rose-800 font-medium px-2 py-1 rounded hover:bg-rose-50 transition-colors"
                            data-testid={`reprocess-btn-${doc.id}`}
                          >
                            <RotateCcw className="w-3.5 h-3.5" />
                            <span>Reprocess</span>
                          </button>
                        )}
                        <Link
                          to={`/documents/${doc.id}`}
                          className="text-sky-600 hover:text-sky-800 font-medium px-2 py-1 rounded hover:bg-sky-50 transition-colors"
                        >
                          View
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="px-6 py-3 border-t border-gray-200 bg-gray-50/50 flex items-center justify-between">
            <span className="text-xs text-gray-500">
              Showing <span className="font-medium">{items.length > 0 ? page * PAGE_SIZE + 1 : 0}</span> to{' '}
              <span className="font-medium">{Math.min((page + 1) * PAGE_SIZE, total)}</span> of{' '}
              <span className="font-medium">{total}</span> documents
            </span>

            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                aria-label="Previous page"
              >
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <span className="text-xs text-gray-600 font-medium">
                Page {totalPages > 0 ? page + 1 : 0} of {totalPages || 1}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => p + 1)}
                disabled={page + 1 >= totalPages}
                aria-label="Next page"
              >
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Upload Modal */}
      <UploadModal
        isOpen={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        onUploadComplete={() => {
          queryClient.invalidateQueries({ queryKey: ['documents'] });
          queryClient.invalidateQueries({ queryKey: ['stats'] });
        }}
      />
    </div>
  );
};
