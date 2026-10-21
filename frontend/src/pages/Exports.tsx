import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, API_BASE_URL, authenticatedFetch } from '../api/client';
import { parseApiError } from '../api/errors';
import { useAuth } from '../auth/useAuth';
import { useToast } from '../components/common/useToast';
import { Button } from '../components/common/Button';
import { Modal } from '../components/common/Modal';
import {
  FileSpreadsheet,
  Download,
  Plus,
  RefreshCw,
  AlertCircle,
  FileText,
  Calendar,
  Layers,
  Info,
} from 'lucide-react';
import type { paths } from '../api/schema';

type ExportBatch =
  paths['/exports']['get']['responses'][200]['content']['application/json']['items'][number];

export const Exports: React.FC = () => {
  const { role } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();

  const isReviewerOrAdmin = role === 'admin' || role === 'reviewer';

  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [selectedFormat, setSelectedFormat] = useState<'csv' | 'json'>('csv');
  const [emptyExportNotice, setEmptyExportNotice] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  // 1. Fetch export batches
  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['export-batches'],
    queryFn: async () => {
      const { data: resData, error: apiErr, response } = await api.GET('/exports', {
        params: { query: { limit: 50, offset: 0 } },
      });
      if (apiErr || !resData) {
        throw parseApiError(apiErr, response?.status);
      }
      return resData;
    },
  });

  const batches = data?.items || [];

  // 2. Create export batch mutation
  const createMutation = useMutation({
    mutationFn: async (format: 'csv' | 'json') => {
      setEmptyExportNotice(null);
      const { data: resData, error: apiErr, response } = await api.POST('/exports', {
        body: { format },
      });

      if (response?.status === 409) {
        throw { isConflict: true, detail: (apiErr as { detail?: string })?.detail };
      }

      if (apiErr || !resData) {
        throw parseApiError(apiErr, response?.status);
      }

      return resData;
    },
    onSuccess: (newBatch) => {
      toast.success(`Export batch created with ${newBatch.row_count} documents.`);
      setIsCreateOpen(false);
      queryClient.invalidateQueries({ queryKey: ['export-batches'] });
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
    },
    onError: (err: unknown) => {
      if ((err as { isConflict?: boolean })?.isConflict) {
        // Show clear friendly message without error toast
        setEmptyExportNotice(
          'No approved or auto-approved invoices are currently eligible for export. Review and approve invoices first.'
        );
        return;
      }
      const parsed = parseApiError(err);
      toast.error(parsed.message || 'Failed to create export batch.');
    },
  });

  // 3. Download helper using authenticated fetch + temporary link
  const handleDownload = async (
    batch: ExportBatch,
    view?: 'summary' | 'line_items'
  ) => {
    const downloadKey = `${batch.id}-${view || 'full'}`;
    setDownloadingId(downloadKey);

    try {
      const queryParam = view ? `?view=${view}` : '';
      const response = await authenticatedFetch(
        `${API_BASE_URL}/exports/${batch.id}/download${queryParam}`
      );

      if (!response.ok) {
        throw new Error(`Download failed with status ${response.status}`);
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;

      const dateStr = new Date(batch.created_at).toISOString().split('T')[0];
      const viewSuffix = view ? `-${view}` : '';
      link.download = `docflow-export-${dateStr}-${batch.id.slice(0, 8)}${viewSuffix}.${batch.format}`;

      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      toast.success('Download started.');
    } catch (err: unknown) {
      const parsed = parseApiError(err);
      toast.error(parsed.message || 'Download failed.');
    } finally {
      setDownloadingId(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Exports</h1>
          <p className="mt-1 text-sm text-gray-500">
            Generate and download standardized accounting summaries and line-item spreadsheets
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
            className="gap-1.5"
            aria-label="Refresh export batches"
          >
            <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </Button>

          {isReviewerOrAdmin && (
            <Button
              size="sm"
              onClick={() => {
                setEmptyExportNotice(null);
                setIsCreateOpen(true);
              }}
              className="gap-1.5"
              data-testid="create-export-btn"
            >
              <Plus className="w-4 h-4" />
              <span>Create Export</span>
            </Button>
          )}
        </div>
      </div>

      {/* Main Content Area */}
      {isLoading ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center shadow-sm">
          <RefreshCw className="w-8 h-8 animate-spin text-sky-600 mx-auto mb-3" />
          <p className="text-sm font-medium text-gray-600">Loading export batches...</p>
        </div>
      ) : isError ? (
        <div className="bg-white rounded-xl border border-rose-200 p-8 text-center shadow-sm">
          <AlertCircle className="w-8 h-8 text-rose-500 mx-auto mb-2" />
          <h3 className="text-base font-semibold text-gray-900">Failed to load exports</h3>
          <p className="text-xs text-rose-600 mt-1">
            {(error as { message?: string })?.message || 'An unexpected error occurred.'}
          </p>
          <Button variant="outline" size="sm" onClick={() => refetch()} className="mt-4">
            Try Again
          </Button>
        </div>
      ) : batches.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center shadow-sm">
          <div className="w-12 h-12 rounded-full bg-sky-50 text-sky-600 mx-auto flex items-center justify-center mb-3">
            <FileSpreadsheet className="w-6 h-6" />
          </div>
          <h3 className="text-base font-semibold text-gray-900">No exports created yet</h3>
          <p className="text-xs text-gray-500 mt-1 max-w-sm mx-auto">
            Approved and auto-approved invoices can be bundled into CSV or JSON export batches.
          </p>
          {isReviewerOrAdmin && (
            <Button
              size="sm"
              onClick={() => {
                setEmptyExportNotice(null);
                setIsCreateOpen(true);
              }}
              className="mt-4 gap-1.5"
            >
              <Plus className="w-4 h-4" />
              <span>Create First Export</span>
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
                    Batch ID
                  </th>
                  <th scope="col" className="px-6 py-3.5">
                    Format
                  </th>
                  <th scope="col" className="px-6 py-3.5">
                    Invoices Included
                  </th>
                  <th scope="col" className="px-6 py-3.5">
                    Created Date
                  </th>
                  <th scope="col" className="px-6 py-3.5 text-right">
                    Download
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {batches.map((batch) => {
                  const isCsv = batch.format === 'csv';
                  const isDownloadingSummary =
                    downloadingId === `${batch.id}-summary`;
                  const isDownloadingLineItems =
                    downloadingId === `${batch.id}-line_items`;
                  const isDownloadingJson = downloadingId === `${batch.id}-full`;

                  return (
                    <tr
                      key={batch.id}
                      className="hover:bg-gray-50/60 transition-colors"
                      data-testid={`export-row-${batch.id}`}
                    >
                      {/* Batch ID */}
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          <FileText className="w-4 h-4 text-gray-400" />
                          <span className="font-mono text-xs font-semibold text-gray-800">
                            {batch.id.slice(0, 8)}…
                          </span>
                        </div>
                      </td>

                      {/* Format Badge */}
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-bold uppercase ${
                            isCsv
                              ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                              : 'bg-purple-50 text-purple-800 border border-purple-200'
                          }`}
                        >
                          {batch.format}
                        </span>
                      </td>

                      {/* Row Count */}
                      <td className="px-6 py-4 whitespace-nowrap text-xs text-gray-700">
                        <div className="flex items-center gap-1.5">
                          <Layers className="w-3.5 h-3.5 text-gray-400" />
                          <span className="font-semibold">{batch.row_count}</span>
                          <span>{batch.row_count === 1 ? 'invoice' : 'invoices'}</span>
                        </div>
                      </td>

                      {/* Created Date */}
                      <td className="px-6 py-4 whitespace-nowrap text-xs text-gray-500">
                        <div className="flex items-center gap-1.5">
                          <Calendar className="w-3.5 h-3.5 text-gray-400" />
                          <span>{new Date(batch.created_at).toLocaleString()}</span>
                        </div>
                      </td>

                      {/* Downloads */}
                      <td className="px-6 py-4 whitespace-nowrap text-right text-xs space-x-2">
                        {isCsv ? (
                          <>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleDownload(batch, 'summary')}
                              disabled={isDownloadingSummary}
                              isLoading={isDownloadingSummary}
                              className="text-xs px-2.5 py-1 gap-1"
                              data-testid={`download-summary-${batch.id}`}
                            >
                              <Download className="w-3.5 h-3.5" />
                              <span>Summary CSV</span>
                            </Button>

                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleDownload(batch, 'line_items')}
                              disabled={isDownloadingLineItems}
                              isLoading={isDownloadingLineItems}
                              className="text-xs px-2.5 py-1 gap-1"
                              data-testid={`download-line-items-${batch.id}`}
                            >
                              <Download className="w-3.5 h-3.5" />
                              <span>Line Items CSV</span>
                            </Button>
                          </>
                        ) : (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleDownload(batch)}
                            disabled={isDownloadingJson}
                            isLoading={isDownloadingJson}
                            className="text-xs px-2.5 py-1 gap-1"
                            data-testid={`download-json-${batch.id}`}
                          >
                            <Download className="w-3.5 h-3.5" />
                            <span>Download JSON</span>
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Create Export Modal */}
      <Modal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        title="Create Export Batch"
        maxWidth="md"
        footer={
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              onClick={() => setIsCreateOpen(false)}
              disabled={createMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              onClick={() => createMutation.mutate(selectedFormat)}
              isLoading={createMutation.isPending}
              data-testid="confirm-create-export-btn"
            >
              Export Invoices
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          <p className="text-xs text-gray-600">
            This will select all currently <strong>approved</strong> and{' '}
            <strong>auto_approved</strong> invoices in your organization, mark them as{' '}
            <strong>exported</strong> (terminal status), and bundle them into a download batch.
          </p>

          {/* 409 Nothing to export friendly notice */}
          {emptyExportNotice && (
            <div
              className="p-3 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-900 flex items-start gap-2"
              role="alert"
              data-testid="nothing-to-export-notice"
            >
              <Info className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
              <span>{emptyExportNotice}</span>
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-2">
              Select Export Format:
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label
                className={`flex flex-col p-3 rounded-xl border cursor-pointer transition-colors ${
                  selectedFormat === 'csv'
                    ? 'border-sky-500 bg-sky-50/50 ring-2 ring-sky-500'
                    : 'border-gray-300 hover:border-gray-400'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-sm text-gray-900">CSV Spreadsheets</span>
                  <input
                    type="radio"
                    name="export-format"
                    value="csv"
                    checked={selectedFormat === 'csv'}
                    onChange={() => setSelectedFormat('csv')}
                    className="text-sky-600 focus:ring-sky-500"
                  />
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  Offers summary and line items views with Excel formula injection defense.
                </p>
              </label>

              <label
                className={`flex flex-col p-3 rounded-xl border cursor-pointer transition-colors ${
                  selectedFormat === 'json'
                    ? 'border-sky-500 bg-sky-50/50 ring-2 ring-sky-500'
                    : 'border-gray-300 hover:border-gray-400'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-sm text-gray-900">Standard JSON</span>
                  <input
                    type="radio"
                    name="export-format"
                    value="json"
                    checked={selectedFormat === 'json'}
                    onChange={() => setSelectedFormat('json')}
                    className="text-sky-600 focus:ring-sky-500"
                  />
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  Full nested invoice data with Decimal strings for ERP and API ingest.
                </p>
              </label>
            </div>
          </div>
        </div>
      </Modal>
    </div>
  );
};
