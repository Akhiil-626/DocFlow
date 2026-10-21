import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { parseApiError } from '../../api/errors';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { History, RefreshCw, AlertCircle, Clock, User, ArrowRight } from 'lucide-react';
import type { paths } from '../../api/schema';

type AuditLogItem =
  paths['/documents/{document_id}/history']['get']['responses'][200]['content']['application/json']['items'][number];

interface HistoryDrawerProps {
  documentId: string;
  isOpen: boolean;
  onClose: () => void;
}

export const HistoryDrawer: React.FC<HistoryDrawerProps> = ({
  documentId,
  isOpen,
  onClose,
}) => {
  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['document-history', documentId],
    queryFn: async () => {
      const { data: resData, error: apiErr, response } = await api.GET(
        '/documents/{document_id}/history',
        {
          params: { path: { document_id: documentId } },
        }
      );
      if (apiErr || !resData) {
        throw parseApiError(apiErr, response?.status);
      }
      return resData;
    },
    enabled: isOpen,
  });

  const items = data?.items || [];

  const formatActionTitle = (action: string) => {
    switch (action) {
      case 'upload_document':
        return 'Document Uploaded';
      case 'edit_extraction':
        return 'Extraction Corrected';
      case 'approve_document':
        return 'Invoice Approved';
      case 'reject_document':
        return 'Invoice Rejected';
      case 'reopen_document':
        return 'Invoice Reopened';
      case 'export_document':
        return 'Document Exported';
      default:
        return action.replace(/_/g, ' ');
    }
  };

  const renderDiffContent = (entry: AuditLogItem) => {
    const newVal = entry.new_value as Record<string, unknown> | null;
    const oldVal = entry.old_value as Record<string, unknown> | null;

    if (!newVal && !oldVal) return null;

    // Field diff from edit_extraction
    const diff = (newVal?.diff || oldVal?.diff) as Record<
      string,
      { old?: unknown; new?: unknown }
    > | undefined;

    if (diff && Object.keys(diff).length > 0) {
      return (
        <div className="mt-2 space-y-1.5 bg-gray-50 p-2.5 rounded-lg border border-gray-200/80 text-xs font-mono">
          <p className="font-sans font-semibold text-[11px] text-gray-500 uppercase">
            Field Modifications:
          </p>
          {Object.entries(diff).map(([field, delta]) => (
            <div key={field} className="flex items-center gap-1.5 flex-wrap">
              <span className="font-semibold text-gray-800">{field}:</span>
              <span className="line-through text-rose-600 bg-rose-50 px-1 rounded">
                {String(delta.old ?? 'empty')}
              </span>
              <ArrowRight className="w-3 h-3 text-gray-400" />
              <span className="text-emerald-700 bg-emerald-50 px-1 rounded font-bold">
                {String(delta.new ?? 'empty')}
              </span>
            </div>
          ))}
          {Boolean(newVal?.note) && (
            <div className="font-sans pt-1 text-gray-600 text-xs italic">
              Note: {String(newVal?.note)}
            </div>
          )}
        </div>
      );
    }

    // Reason / Note
    const reason = newVal?.reason || newVal?.review_note;
    if (reason) {
      return (
        <div className="mt-1.5 bg-gray-50 p-2 rounded text-xs text-gray-700 border border-gray-200">
          <span className="font-semibold">Reason:</span> {String(reason)}
        </div>
      );
    }

    return null;
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Document Audit History"
      maxWidth="lg"
      footer={
        <div className="flex justify-between items-center w-full">
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
            className="gap-1.5"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </Button>
          <Button variant="secondary" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      }
    >
      <div className="space-y-4 max-h-[65vh] overflow-y-auto pr-1">
        {isLoading ? (
          <div className="py-12 text-center text-gray-500">
            <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-sky-600" />
            <p className="text-xs">Loading audit events...</p>
          </div>
        ) : isError ? (
          <div className="py-8 text-center text-rose-600">
            <AlertCircle className="w-6 h-6 mx-auto mb-2 text-rose-500" />
            <p className="text-xs">{(error as { message?: string })?.message || 'Failed to load audit history'}</p>
          </div>
        ) : items.length === 0 ? (
          <div className="py-12 text-center text-gray-400">
            <History className="w-8 h-8 mx-auto mb-2 text-gray-300" />
            <p className="text-xs font-medium">No history entries recorded for this document.</p>
          </div>
        ) : (
          <div className="relative pl-6 space-y-6 before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-gray-200">
            {items.map((entry) => (
              <div key={entry.id} className="relative group text-sm" data-testid="history-entry">
                {/* Node icon */}
                <div className="absolute -left-6 top-1 w-5 h-5 rounded-full bg-white border-2 border-sky-600 flex items-center justify-center">
                  <div className="w-1.5 h-1.5 rounded-full bg-sky-600" />
                </div>

                {/* Entry header */}
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-gray-900 capitalize">
                    {formatActionTitle(entry.action)}
                  </span>
                  <span className="text-[11px] text-gray-400 flex items-center gap-1 shrink-0">
                    <Clock className="w-3 h-3" />
                    {new Date(entry.created_at).toLocaleString()}
                  </span>
                </div>

                {/* Actor */}
                <div className="text-xs text-gray-500 flex items-center gap-1 mt-0.5">
                  <User className="w-3 h-3 text-gray-400" />
                  <span>{entry.actor_email || 'system'}</span>
                </div>

                {/* Diff details */}
                {renderDiffContent(entry)}
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
};
