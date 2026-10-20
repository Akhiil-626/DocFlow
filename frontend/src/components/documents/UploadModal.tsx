import React, { useState, useRef } from 'react';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { Upload, FileText, CheckCircle2, AlertCircle, Copy, ArrowRight } from 'lucide-react';
import { API_BASE_URL, getAccessToken } from '../../api/client';
import { parseApiError } from '../../api/errors';
import { useToast } from '../common/useToast';
import { Link } from 'react-router-dom';

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
const ALLOWED_MIME_TYPES = ['application/pdf', 'image/png', 'image/jpeg'];
const ALLOWED_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg'];

interface UploadResult {
  filename: string;
  success: boolean;
  documentId?: string;
  existingDocumentId?: string | null;
  errorMessage?: string;
}

interface UploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onUploadComplete?: () => void;
}

export const UploadModal: React.FC<UploadModalProps> = ({
  isOpen,
  onClose,
  onUploadComplete,
}) => {
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [isDragging, setIsDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [clientError, setClientError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [result, setResult] = useState<UploadResult | null>(null);

  const resetState = () => {
    setSelectedFile(null);
    setClientError(null);
    setIsUploading(false);
    setUploadProgress(0);
    setResult(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleClose = () => {
    resetState();
    onClose();
  };

  const validateFile = (file: File): boolean => {
    setClientError(null);
    setResult(null);

    // 1. File size check
    if (file.size > MAX_FILE_SIZE) {
      setClientError(
        `File size exceeds 10 MB limit (${(file.size / (1024 * 1024)).toFixed(1)} MB).`
      );
      return false;
    }

    // 2. MIME type & extension check
    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    const isMimeValid = ALLOWED_MIME_TYPES.includes(file.type);
    const isExtValid = ALLOWED_EXTENSIONS.includes(ext);

    if (!isMimeValid && !isExtValid) {
      setClientError('Invalid file type. Only authentic PDF, PNG, and JPEG files are supported.');
      return false;
    }

    return true;
  };

  const handleFileSelect = (file: File) => {
    if (validateFile(file)) {
      setSelectedFile(file);
    } else {
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleUpload = () => {
    if (!selectedFile) return;

    setIsUploading(true);
    setUploadProgress(0);
    setClientError(null);

    const formData = new FormData();
    formData.append('file', selectedFile);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE_URL}/documents`);
    xhr.withCredentials = true;

    const token = getAccessToken();
    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    }

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        const percent = Math.round((event.loaded / event.total) * 100);
        setUploadProgress(percent);
      }
    };

    xhr.onload = () => {
      setIsUploading(false);
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status === 201 || xhr.status === 200) {
          const res: UploadResult = {
            filename: selectedFile.name,
            success: true,
            documentId: data.id,
            existingDocumentId: data.existing_document_id,
          };
          setResult(res);

          if (data.existing_document_id) {
            toast.info('Exact duplicate invoice detected.');
          } else {
            toast.success('Invoice uploaded successfully.');
          }
          onUploadComplete?.();
        } else {
          const parsed = parseApiError(data, xhr.status);
          setResult({
            filename: selectedFile.name,
            success: false,
            errorMessage: parsed.message,
          });
          toast.error(parsed.message || 'Upload failed.');
        }
      } catch {
        setResult({
          filename: selectedFile.name,
          success: false,
          errorMessage: 'Failed to process server response.',
        });
        toast.error('Failed to parse upload response.');
      }
    };

    xhr.onerror = () => {
      setIsUploading(false);
      const parsed = parseApiError(new TypeError('Network request failed'));
      setResult({
        filename: selectedFile.name,
        success: false,
        errorMessage: parsed.message,
      });
      toast.error(parsed.message);
    };

    xhr.send(formData);
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title="Upload Invoice"
      maxWidth="md"
      footer={
        <div className="flex gap-2">
          <Button variant="secondary" onClick={handleClose} disabled={isUploading}>
            {result?.success ? 'Close' : 'Cancel'}
          </Button>
          {!result?.success && (
            <Button
              onClick={handleUpload}
              disabled={!selectedFile || isUploading}
              isLoading={isUploading}
            >
              Start Upload
            </Button>
          )}
        </div>
      }
    >
      <div className="space-y-4">
        {/* Dropzone */}
        {!result && (
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
              isDragging
                ? 'border-sky-500 bg-sky-50/50'
                : 'border-gray-300 hover:border-gray-400 bg-gray-50/50'
            }`}
            data-testid="upload-dropzone"
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
              className="hidden"
              onChange={(e) => {
                if (e.target.files && e.target.files[0]) {
                  handleFileSelect(e.target.files[0]);
                }
              }}
              data-testid="file-picker-input"
            />
            <div className="w-12 h-12 rounded-full bg-sky-100 text-sky-600 mx-auto flex items-center justify-center mb-3">
              <Upload className="w-6 h-6" />
            </div>
            <p className="text-sm font-semibold text-gray-700">
              Drag and drop your invoice here, or click to browse
            </p>
            <p className="text-xs text-gray-500 mt-1">
              Supports PDF, PNG, or JPEG (Max 10 MB)
            </p>
          </div>
        )}

        {/* Selected file preview */}
        {selectedFile && !result && (
          <div className="p-3 bg-gray-50 border border-gray-200 rounded-lg flex items-center justify-between">
            <div className="flex items-center gap-3 overflow-hidden">
              <FileText className="w-5 h-5 text-sky-600 shrink-0" />
              <div className="truncate text-sm">
                <span className="font-medium text-gray-900 truncate block">
                  {selectedFile.name}
                </span>
                <span className="text-xs text-gray-500">
                  {(selectedFile.size / 1024).toFixed(0)} KB
                </span>
              </div>
            </div>
            {!isUploading && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  resetState();
                }}
                className="text-xs text-gray-500 hover:text-gray-700 font-medium px-2 py-1 rounded"
              >
                Change
              </button>
            )}
          </div>
        )}

        {/* Client Error */}
        {clientError && (
          <div
            className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-sm text-rose-800 flex items-start gap-2"
            role="alert"
          >
            <AlertCircle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
            <span>{clientError}</span>
          </div>
        )}

        {/* Progress bar */}
        {isUploading && (
          <div className="space-y-1.5" data-testid="upload-progress-container">
            <div className="flex justify-between text-xs text-gray-600 font-medium">
              <span>Uploading invoice...</span>
              <span>{uploadProgress}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
              <div
                className="bg-sky-600 h-2 rounded-full transition-all duration-150"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
          </div>
        )}

        {/* Result view */}
        {result && (
          <div className="space-y-3">
            {result.success ? (
              <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-xl">
                <div className="flex items-center gap-2 text-emerald-800 font-semibold text-sm">
                  <CheckCircle2 className="w-5 h-5 text-emerald-600" />
                  <span>Upload Successful</span>
                </div>
                <p className="text-xs text-emerald-700 mt-1">
                  Invoice <span className="font-mono">{result.filename}</span> is queued for background extraction.
                </p>

                {/* Duplicate Notification */}
                {result.existingDocumentId && (
                  <div
                    className="mt-3 p-3 bg-amber-50 border border-amber-200 rounded-lg text-amber-900 text-xs"
                    data-testid="duplicate-notice"
                  >
                    <div className="flex items-center gap-1.5 font-semibold">
                      <Copy className="w-4 h-4 text-amber-700" />
                      <span>Exact Duplicate Detected</span>
                    </div>
                    <p className="mt-1 text-amber-800">
                      This file matches an invoice already in your system.
                    </p>
                    <Link
                      to={`/documents/${result.existingDocumentId}`}
                      onClick={handleClose}
                      className="mt-2 inline-flex items-center gap-1 text-sky-700 font-medium hover:underline"
                    >
                      <span>View existing document</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </Link>
                  </div>
                )}
              </div>
            ) : (
              <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl">
                <div className="flex items-center gap-2 text-rose-800 font-semibold text-sm">
                  <AlertCircle className="w-5 h-5 text-rose-600" />
                  <span>Upload Failed</span>
                </div>
                <p className="text-xs text-rose-700 mt-1">
                  {result.errorMessage || 'An error occurred during upload.'}
                </p>
                <div className="mt-3">
                  <Button size="sm" variant="outline" onClick={resetState}>
                    Try Again
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
};
