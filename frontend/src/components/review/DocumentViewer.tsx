import React, { useEffect, useState, useCallback } from 'react';
import { API_BASE_URL, authenticatedFetch } from '../../api/client';
import { RefreshCw, AlertCircle, FileText } from 'lucide-react';
import { Button } from '../common/Button';

interface DocumentViewerProps {
  documentId: string;
  contentType: string;
  filename: string;
}

export const DocumentViewer: React.FC<DocumentViewerProps> = ({
  documentId,
  contentType,
  filename,
}) => {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDocumentFile = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await authenticatedFetch(
        `${API_BASE_URL}/documents/${documentId}/file`
      );

      if (!response.ok) {
        if (response.status === 404) {
          throw new Error('Document file not found on storage.');
        }
        throw new Error(`Failed to load document (HTTP ${response.status})`);
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      setBlobUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return url;
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to retrieve file binary';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [documentId]);

  useEffect(() => {
    fetchDocumentFile();
    return () => {
      setBlobUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
    };
  }, [fetchDocumentFile]);

  const isPdf =
    contentType.includes('pdf') || filename.toLowerCase().endsWith('.pdf');
  const isImage =
    contentType.includes('image') ||
    filename.toLowerCase().endsWith('.png') ||
    filename.toLowerCase().endsWith('.jpg') ||
    filename.toLowerCase().endsWith('.jpeg');

  if (isLoading) {
    return (
      <div className="h-full min-h-[500px] flex flex-col items-center justify-center bg-gray-100 rounded-xl border border-gray-200 p-8 text-center">
        <RefreshCw className="w-8 h-8 animate-spin text-sky-600 mb-3" />
        <p className="text-sm font-medium text-gray-700">Loading original invoice file...</p>
        <span className="text-xs text-gray-400 mt-1">{filename}</span>
      </div>
    );
  }

  if (error || !blobUrl) {
    return (
      <div className="h-full min-h-[500px] flex flex-col items-center justify-center bg-gray-50 rounded-xl border border-rose-200 p-8 text-center">
        <AlertCircle className="w-8 h-8 text-rose-500 mb-2" />
        <h4 className="text-sm font-semibold text-gray-900">Unable to preview document</h4>
        <p className="text-xs text-rose-600 mt-1 max-w-sm">{error || 'Unknown error'}</p>
        <Button
          variant="outline"
          size="sm"
          onClick={fetchDocumentFile}
          className="mt-4"
        >
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="h-full min-h-[500px] flex flex-col bg-gray-100 rounded-xl border border-gray-200 overflow-hidden shadow-inner">
      <div className="bg-gray-200/80 px-4 py-2 border-b border-gray-300 flex items-center justify-between text-xs text-gray-600 font-medium">
        <div className="flex items-center gap-2 truncate">
          <FileText className="w-4 h-4 text-gray-500 shrink-0" />
          <span className="truncate" title={filename}>
            {filename}
          </span>
        </div>
        <span className="shrink-0 uppercase px-1.5 py-0.5 rounded bg-gray-300 text-[10px] font-bold">
          {isPdf ? 'PDF' : isImage ? 'IMAGE' : 'DOCUMENT'}
        </span>
      </div>

      <div className="flex-1 w-full h-full relative overflow-auto bg-gray-900/5 flex items-center justify-center">
        {isPdf ? (
          <iframe
            src={`${blobUrl}#toolbar=0&navpanes=0`}
            title={`Preview of ${filename}`}
            className="w-full h-full min-h-[600px] border-0"
            data-testid="pdf-preview-frame"
          />
        ) : isImage ? (
          <img
            src={blobUrl}
            alt={filename}
            className="max-w-full max-h-[800px] object-contain p-4"
            data-testid="image-preview"
          />
        ) : (
          <div className="p-8 text-center">
            <p className="text-sm text-gray-600">
              Preview not available directly for this file format.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};
