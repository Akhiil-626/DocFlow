import React from 'react';
import { clsx } from 'clsx';
import {
  Upload,
  Loader2,
  FileCheck2,
  AlertCircle,
  CheckCircle2,
  ThumbsUp,
  XCircle,
  AlertOctagon,
  Archive,
} from 'lucide-react';

export type DocumentStatus =
  | 'uploaded'
  | 'processing'
  | 'extracted'
  | 'needs_review'
  | 'auto_approved'
  | 'approved'
  | 'rejected'
  | 'failed'
  | 'exported';

interface StatusBadgeProps {
  status: string;
  className?: string;
  showIcon?: boolean;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  className,
  showIcon = true,
}) => {
  const normStatus = (status || '').toLowerCase() as DocumentStatus;

  const config: Record<
    DocumentStatus,
    { label: string; icon: React.ReactNode; bg: string; text: string; border: string }
  > = {
    uploaded: {
      label: 'Uploaded',
      icon: <Upload className="w-3.5 h-3.5" />,
      bg: 'bg-slate-100',
      text: 'text-slate-700',
      border: 'border-slate-300',
    },
    processing: {
      label: 'Processing',
      icon: <Loader2 className="w-3.5 h-3.5 animate-spin" />,
      bg: 'bg-blue-50',
      text: 'text-blue-700',
      border: 'border-blue-200',
    },
    extracted: {
      label: 'Extracted',
      icon: <FileCheck2 className="w-3.5 h-3.5" />,
      bg: 'bg-indigo-50',
      text: 'text-indigo-700',
      border: 'border-indigo-200',
    },
    needs_review: {
      label: 'Needs Review',
      icon: <AlertCircle className="w-3.5 h-3.5" />,
      bg: 'bg-amber-50',
      text: 'text-amber-800',
      border: 'border-amber-300',
    },
    auto_approved: {
      label: 'Auto Approved',
      icon: <CheckCircle2 className="w-3.5 h-3.5" />,
      bg: 'bg-emerald-50',
      text: 'text-emerald-700',
      border: 'border-emerald-200',
    },
    approved: {
      label: 'Approved',
      icon: <ThumbsUp className="w-3.5 h-3.5" />,
      bg: 'bg-green-50',
      text: 'text-green-800',
      border: 'border-green-300',
    },
    rejected: {
      label: 'Rejected',
      icon: <XCircle className="w-3.5 h-3.5" />,
      bg: 'bg-rose-50',
      text: 'text-rose-700',
      border: 'border-rose-200',
    },
    failed: {
      label: 'Failed',
      icon: <AlertOctagon className="w-3.5 h-3.5" />,
      bg: 'bg-red-100',
      text: 'text-red-800',
      border: 'border-red-300',
    },
    exported: {
      label: 'Exported',
      icon: <Archive className="w-3.5 h-3.5" />,
      bg: 'bg-purple-50',
      text: 'text-purple-700',
      border: 'border-purple-200',
    },
  };

  const item = config[normStatus] || {
    label: status,
    icon: null,
    bg: 'bg-gray-100',
    text: 'text-gray-700',
    border: 'border-gray-200',
  };

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border',
        item.bg,
        item.text,
        item.border,
        className
      )}
      data-testid={`status-badge-${normStatus}`}
    >
      {showIcon && item.icon}
      <span>{item.label}</span>
    </span>
  );
};
