import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { parseApiError } from '../api/errors';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { StatusBadge } from '../components/common/StatusBadge';
import {
  FileText,
  CheckCircle2,
  AlertCircle,
  ThumbsUp,
  XCircle,
  Percent,
  RefreshCw,
  TrendingUp,
} from 'lucide-react';

export const Dashboard: React.FC = () => {
  const {
    data: stats,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['stats'],
    queryFn: async () => {
      const { data, error: apiErr, response } = await api.GET('/stats');
      if (apiErr || !data) {
        throw parseApiError(apiErr, (response as Response | undefined)?.status);
      }
      return data;
    },
  });

  if (isLoading) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-12 text-center shadow-sm">
        <RefreshCw className="w-8 h-8 animate-spin text-sky-600 mx-auto mb-3" />
        <p className="text-sm font-medium text-gray-600">Loading metrics and statistics...</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="bg-white rounded-xl border border-rose-200 p-8 text-center shadow-sm">
        <AlertCircle className="w-8 h-8 text-rose-500 mx-auto mb-2" />
        <h3 className="text-base font-semibold text-gray-900">Failed to load dashboard metrics</h3>
        <p className="text-xs text-gray-500 mt-1 max-w-md mx-auto">
          {(error as { message?: string })?.message || 'An unexpected error occurred.'}
        </p>
        <Button variant="outline" size="sm" onClick={() => refetch()} className="mt-4">
          Try Again
        </Button>
      </div>
    );
  }

  const counts = stats?.counts || {};
  const total = stats?.total ?? 0;
  const autoApprovalRate = stats ? (stats.auto_approval_rate * 100).toFixed(1) : '0.0';
  const correctionRate = stats?.correction_rate !== undefined
    ? (stats.correction_rate * 100).toFixed(1)
    : null;
  const topFields = stats?.top_corrected_fields || [];

  const statusOrder = [
    'auto_approved',
    'needs_review',
    'approved',
    'rejected',
    'exported',
    'uploaded',
    'processing',
    'failed',
  ];

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Dashboard</h1>
          <p className="mt-1 text-sm text-gray-500">
            Real-time pipeline performance, automation rates, and human review analytics
          </p>
        </div>

        <Button
          variant="outline"
          size="sm"
          onClick={() => refetch()}
          disabled={isFetching}
          className="gap-1.5 self-start sm:self-auto"
          aria-label="Refresh dashboard metrics"
        >
          <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
          <span>Refresh Metrics</span>
        </Button>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Invoices */}
        <Card className="border-l-4 border-l-sky-500">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Total Documents
              </p>
              <h2 className="text-2xl font-bold text-gray-900 mt-1" data-testid="stat-total">
                {total}
              </h2>
            </div>
            <div className="w-10 h-10 rounded-lg bg-sky-50 text-sky-600 flex items-center justify-center">
              <FileText className="w-5 h-5" />
            </div>
          </div>
        </Card>

        {/* Auto-Approval Rate */}
        <Card className="border-l-4 border-l-emerald-500">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Auto-Approval Rate
              </p>
              <h2 className="text-2xl font-bold text-gray-900 mt-1" data-testid="stat-auto-approval">
                {autoApprovalRate}%
              </h2>
            </div>
            <div className="w-10 h-10 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center">
              <CheckCircle2 className="w-5 h-5" />
            </div>
          </div>
        </Card>

        {/* Documents Reviewed */}
        <Card className="border-l-4 border-l-purple-500">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Human Reviews
              </p>
              <h2 className="text-2xl font-bold text-gray-900 mt-1" data-testid="stat-reviewed">
                {stats?.documents_reviewed ?? 0}
              </h2>
            </div>
            <div className="w-10 h-10 rounded-lg bg-purple-50 text-purple-600 flex items-center justify-center">
              <TrendingUp className="w-5 h-5" />
            </div>
          </div>
        </Card>

        {/* Human Correction Rate */}
        <Card className="border-l-4 border-l-amber-500">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Correction Rate
              </p>
              <h2 className="text-2xl font-bold text-gray-900 mt-1" data-testid="stat-correction-rate">
                {correctionRate !== null ? `${correctionRate}%` : '—'}
              </h2>
            </div>
            <div className="w-10 h-10 rounded-lg bg-amber-50 text-amber-600 flex items-center justify-center">
              <Percent className="w-5 h-5" />
            </div>
          </div>
        </Card>
      </div>

      {/* Breakdown Details Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Status Distribution */}
        <Card
          title="Document Status Breakdown"
          subtitle="Distribution of documents across extraction and review stages"
        >
          <div className="space-y-3">
            {statusOrder.map((st) => {
              const count = counts[st] ?? 0;
              const pct = total > 0 ? ((count / total) * 100).toFixed(0) : '0';

              return (
                <div key={st} className="flex flex-col gap-1">
                  <div className="flex items-center justify-between text-xs">
                    <StatusBadge status={st} showIcon={false} />
                    <span className="font-semibold text-gray-700">
                      {count}{' '}
                      <span className="text-gray-400 font-normal">({pct}%)</span>
                    </span>
                  </div>
                  <div className="w-full bg-gray-100 rounded-full h-1.5 overflow-hidden">
                    <div
                      className={`h-1.5 rounded-full ${
                        st === 'auto_approved' || st === 'approved'
                          ? 'bg-emerald-500'
                          : st === 'needs_review'
                            ? 'bg-amber-500'
                            : st === 'rejected' || st === 'failed'
                              ? 'bg-rose-500'
                              : 'bg-sky-500'
                      }`}
                      style={{ width: `${Math.min(100, Number(pct))}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </Card>

        {/* Human Review Decisions & Top Corrected Fields */}
        <div className="space-y-6">
          {/* Review Decisions */}
          <Card
            title="Review Outcomes"
            subtitle="Resolution of manually inspected invoices"
          >
            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 bg-emerald-50/70 border border-emerald-100 rounded-xl flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center shrink-0">
                  <ThumbsUp className="w-5 h-5" />
                </div>
                <div>
                  <span className="text-xs font-medium text-emerald-800">Approved</span>
                  <p className="text-xl font-bold text-emerald-900" data-testid="stat-approved-count">
                    {stats?.approved_count ?? 0}
                  </p>
                </div>
              </div>

              <div className="p-4 bg-rose-50/70 border border-rose-100 rounded-xl flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-rose-100 text-rose-700 flex items-center justify-center shrink-0">
                  <XCircle className="w-5 h-5" />
                </div>
                <div>
                  <span className="text-xs font-medium text-rose-800">Rejected</span>
                  <p className="text-xl font-bold text-rose-900" data-testid="stat-rejected-count">
                    {stats?.rejected_count ?? 0}
                  </p>
                </div>
              </div>
            </div>
          </Card>

          {/* Top Corrected Fields */}
          <Card
            title="Most Corrected Fields"
            subtitle="Fields reviewers modified most often during inspection"
          >
            {topFields.length === 0 ? (
              <p className="text-xs text-gray-400 italic text-center py-4">
                No human field corrections recorded yet.
              </p>
            ) : (
              <div className="space-y-2.5" data-testid="top-corrected-fields">
                {topFields.map((item) => (
                  <div
                    key={item.field}
                    className="flex items-center justify-between text-xs py-1.5 px-3 bg-gray-50 rounded-lg border border-gray-100"
                  >
                    <span className="font-mono text-gray-800 font-medium">{item.field}</span>
                    <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-amber-100 text-amber-800">
                      {item.count} {item.count === 1 ? 'correction' : 'corrections'}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
};
