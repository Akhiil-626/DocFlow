import React, { forwardRef } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, AlertTriangle } from 'lucide-react';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  warning?: string;
  helperText?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, warning, helperText, className, id, ...props }, ref) => {
    const inputId = id || (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined);

    return (
      <div className="w-full">
        {label && (
          <label htmlFor={inputId} className="block text-sm font-medium text-gray-700 mb-1">
            {label}
            {props.required && <span className="text-rose-500 ml-1">*</span>}
          </label>
        )}
        <div className="relative">
          <input
            id={inputId}
            ref={ref}
            className={clsx(
              'w-full rounded-lg border px-3 py-2 text-sm shadow-sm transition-colors',
              'focus:outline-none focus:ring-2 focus:ring-offset-1',
              error
                ? 'border-rose-400 text-rose-900 focus:border-rose-500 focus:ring-rose-500 bg-rose-50/30'
                : warning
                  ? 'border-amber-400 text-amber-900 focus:border-amber-500 focus:ring-amber-500 bg-amber-50/30'
                  : 'border-gray-300 focus:border-sky-500 focus:ring-sky-500 bg-white',
              className
            )}
            aria-invalid={!!error}
            aria-describedby={
              error ? `${inputId}-error` : warning ? `${inputId}-warning` : undefined
            }
            {...props}
          />
          {error && (
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-3">
              <AlertCircle className="h-4 w-4 text-rose-500" aria-hidden="true" />
            </div>
          )}
          {!error && warning && (
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-3">
              <AlertTriangle className="h-4 w-4 text-amber-500" aria-hidden="true" />
            </div>
          )}
        </div>
        {error && (
          <p id={`${inputId}-error`} className="mt-1 text-xs text-rose-600 flex items-center gap-1">
            <span>{error}</span>
          </p>
        )}
        {!error && warning && (
          <p id={`${inputId}-warning`} className="mt-1 text-xs text-amber-600 flex items-center gap-1">
            <span>{warning}</span>
          </p>
        )}
        {!error && !warning && helperText && (
          <p className="mt-1 text-xs text-gray-500">{helperText}</p>
        )}
      </div>
    );
  }
);

Input.displayName = 'Input';
