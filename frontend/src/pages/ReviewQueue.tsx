import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { parseApiError } from '../api/errors';
import { StatusBadge } from '../components/common/StatusBadge';
import { Button } from '../components/common/Button';
import {
  Inbox,
  RefreshCw,
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  ShieldAlert,
} from 'lucide-react';

export const ReviewQueue: React.FC = () => {
  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['review-queue'],
    queryFn: async () => {
      const { data: resData, error: apiErr, response } = await api.GET(
        '/documents/review-queue'
      );
      if (apiErr || !resData) {
        throw parseApiError(apiErr, (response as Response | undefined)?.status);
      }
      return resData;
    },
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Review Queue</h1>
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 border border-amber-200">
              {total} pending
            </span>
          </div>
          <p className="mt-1 text-sm text-gray-500">
            Oldest invoices requiring human verification first (FIFO)
          </p>
        </div>

        <Button
          variant="outline"
          size="sm"
          onClick={() => refetch()}
          disabled={isFetching}
          className="gap-1.5 self-start sm:self-auto"
          aria-label="Refresh review queue"
        >
          <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
          <span>Refresh Queue</span>
        </Button>
      </div>

      {/* Main Content */}
      {isLoading ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center shadow-sm">
          <RefreshCw className="w-8 h-8 animate-spin text-sky-600 mx-auto mb-3" />
          <p className="text-sm font-medium text-gray-600">Loading review queue...</p>
        </div>
      ) : isError ? (
        <div className="bg-white rounded-xl border border-rose-200 p-8 text-center shadow-sm">
          <AlertCircle className="w-8 h-8 text-rose-500 mx-auto mb-2" />
          <h3 className="text-base font-semibold text-gray-900">Failed to load review queue</h3>
          <p className="text-xs text-gray-500 mt-1 max-w-md mx-auto">
            {(error as { message?: string })?.message || 'An unexpected error occurred.'}
          </p>
          <Button variant="outline" size="sm" onClick={() => refetch()} className="mt-4">
            Try Again
          </Button>
        </div>
      ) : items.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center shadow-sm">
          <div className="w-12 h-12 rounded-full bg-emerald-50 text-emerald-600 mx-auto flex items-center justify-center mb-3">
            <Inbox className="w-6 h-6" />
          </div>
          <h3 className="text-base font-semibold text-gray-900">All caught up!</h3>
          <p className="text-xs text-gray-500 mt-1 max-w-sm mx-auto">
            There are currently no invoices in needs_review status. High-confidence invoices
            have been auto-approved.
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-left text-sm">
              <thead className="bg-gray-50/75 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                <tr>
                  <th scope="col" className="px-6 py-3.5">
                    Filename
                  </th>
                  <th scope="col" className="px-6 py-3.5">
                    Issues
                  </th>
                  <th scope="col" className="px-6 py-3.5">
                    Review Reason
                  </th>
                  <th scope="col" className="px-6 py-3.5">
                    Queue Age
                  </th>
                  <th scope="col" className="px-6 py-3.5 text-right">
                    Action
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {items.map((doc) => {
                  const errorCount = (doc.issues || []).filter(
                    (i) => i.severity === 'error'
                  ).length;
                  const warningCount = (doc.issues || []).filter(
                    (i) => i.severity === 'warning'
                  ).length;

                  return (
                    <tr
                      key={doc.id}
                      className="hover:bg-gray-50/60 transition-colors"
                      data-testid={`queue-row-${doc.id}`}
                    >
                      {/* Filename (Untrusted plain text) */}
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center gap-3">
                          <StatusBadge status={doc.status} showIcon={false} />
                          <div>
                            <span
                              className="font-medium text-gray-900 block truncate max-w-xs"
                              title={doc.original_filename}
                            >
                              {doc.original_filename}
                            </span>
                          </div>
                        </div>
                      </td>

                      {/* Issue Count Badges */}
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          {errorCount > 0 && (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200">
                              <ShieldAlert className="w-3.5 h-3.5" />
                              <span>{errorCount} {errorCount === 1 ? 'Error' : 'Errors'}</span>
                            </span>
                          )}
                          {warningCount > 0 && (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-amber-50 text-amber-800 border border-amber-200">
                              <AlertTriangle className="w-3.5 h-3.5" />
                              <span>{warningCount} {warningCount === 1 ? 'Warning' : 'Warnings'}</span>
                            </span>
                          )}
                          {doc.issue_count === 0 && (
                            <span className="text-xs text-gray-400">None</span>
                          )}
                        </div>
                      </td>

                      {/* Review Reason */}
                      <td className="px-6 py-4 text-xs max-w-sm">
                        <span className="text-gray-700 line-clamp-2" title={doc.review_reason || ''}>
                          {doc.review_reason || 'Manual review required'}
                        </span>
                      </td>

                      {/* Queue Age */}
                      <td className="px-6 py-4 whitespace-nowrap text-xs text-gray-500">
                        {new Date(doc.created_at).toLocaleDateString(undefined, {
                          month: 'short',
                          day: 'numeric',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </td>

                      {/* Review Action */}
                      <td className="px-6 py-4 whitespace-nowrap text-right text-xs">
                        <Link
                          to={`/documents/${doc.id}`}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-700 text-white font-medium transition-colors shadow-sm"
                          data-testid={`review-btn-${doc.id}`}
                        >
                          <span>Review</span>
                          <ArrowRight className="w-3.5 h-3.5" />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
