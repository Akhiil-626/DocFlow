import React from 'react';
import { Loader2 } from 'lucide-react';

export const LoadingScreen: React.FC<{ message?: string }> = ({ message = 'Loading DocFlow...' }) => {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 text-gray-700">
      <div className="flex flex-col items-center gap-3">
        <Loader2 className="w-10 h-10 animate-spin text-sky-600" />
        <p className="text-sm font-medium text-gray-600">{message}</p>
      </div>
    </div>
  );
};
