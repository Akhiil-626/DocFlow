import React from 'react';
import { ShieldAlert, AlertTriangle, ArrowDownRight } from 'lucide-react';
import type { paths } from '../../api/schema';

type ValidationIssue =
  NonNullable<paths['/documents/{document_id}/extraction']['get']['responses'][200]['content']['application/json']['validation_issues']>[number];

interface IssuesPanelProps {
  issues: ValidationIssue[];
  onSelectField?: (field: string) => void;
}

export const IssuesPanel: React.FC<IssuesPanelProps> = ({ issues, onSelectField }) => {
  if (!issues || issues.length === 0) {
    return null;
  }

  const errors = issues.filter((i) => i.severity === 'error');
  const warnings = issues.filter((i) => i.severity === 'warning');

  const handleIssueClick = (field: string | null | undefined) => {
    if (field && onSelectField) {
      onSelectField(field);
    }
  };

  return (
    <div className="space-y-3" data-testid="issues-panel">
      {/* Errors Section (Always first) */}
      {errors.length > 0 && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl space-y-2">
          <div className="flex items-center gap-2 text-rose-800 text-sm font-semibold">
            <ShieldAlert className="w-4 h-4 text-rose-600 shrink-0" />
            <span>
              {errors.length} {errors.length === 1 ? 'Error' : 'Errors'} Requiring Attention
            </span>
          </div>
          <div className="space-y-1.5 divide-y divide-rose-100">
            {errors.map((issue) => (
              <div
                key={issue.id}
                onClick={() => handleIssueClick(issue.field)}
                className={`pt-1.5 first:pt-0 flex items-start justify-between gap-3 text-xs text-rose-900 ${
                  issue.field
                    ? 'cursor-pointer hover:bg-rose-100/50 p-1.5 rounded transition-colors'
                    : 'p-1.5'
                }`}
                title={issue.field ? `Click to jump to ${issue.field}` : undefined}
                role={issue.field ? 'button' : undefined}
                tabIndex={issue.field ? 0 : undefined}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    handleIssueClick(issue.field);
                  }
                }}
                data-testid={`issue-item-${issue.code}`}
              >
                <div className="space-y-0.5">
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono font-bold text-[11px] bg-rose-200/80 text-rose-800 px-1.5 py-0.5 rounded">
                      {issue.code}
                    </span>
                    {issue.field && (
                      <span className="font-semibold text-rose-700">
                        [{issue.field}]
                      </span>
                    )}
                  </div>
                  <p className="text-rose-800">{issue.message}</p>
                </div>
                {issue.field && (
                  <span className="shrink-0 text-rose-600 inline-flex items-center gap-0.5 mt-0.5 text-[11px] font-medium">
                    <span>Jump</span>
                    <ArrowDownRight className="w-3.5 h-3.5" />
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Warnings Section */}
      {warnings.length > 0 && (
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl space-y-2">
          <div className="flex items-center gap-2 text-amber-800 text-sm font-semibold">
            <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
            <span>
              {warnings.length} {warnings.length === 1 ? 'Warning' : 'Warnings'} Detected
            </span>
          </div>
          <div className="space-y-1.5 divide-y divide-amber-100">
            {warnings.map((issue) => (
              <div
                key={issue.id}
                onClick={() => handleIssueClick(issue.field)}
                className={`pt-1.5 first:pt-0 flex items-start justify-between gap-3 text-xs text-amber-900 ${
                  issue.field
                    ? 'cursor-pointer hover:bg-amber-100/50 p-1.5 rounded transition-colors'
                    : 'p-1.5'
                }`}
                title={issue.field ? `Click to jump to ${issue.field}` : undefined}
                role={issue.field ? 'button' : undefined}
                tabIndex={issue.field ? 0 : undefined}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    handleIssueClick(issue.field);
                  }
                }}
                data-testid={`issue-item-${issue.code}`}
              >
                <div className="space-y-0.5">
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono font-bold text-[11px] bg-amber-200/80 text-amber-900 px-1.5 py-0.5 rounded">
                      {issue.code}
                    </span>
                    {issue.field && (
                      <span className="font-semibold text-amber-800">
                        [{issue.field}]
                      </span>
                    )}
                  </div>
                  <p className="text-amber-800">{issue.message}</p>
                </div>
                {issue.field && (
                  <span className="shrink-0 text-amber-700 inline-flex items-center gap-0.5 mt-0.5 text-[11px] font-medium">
                    <span>Jump</span>
                    <ArrowDownRight className="w-3.5 h-3.5" />
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
