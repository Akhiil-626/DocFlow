import React from 'react';
import { useParams } from 'react-router-dom';

export const ReviewScreen: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">Review Invoice</h1>
      <p className="mt-1 text-sm text-gray-500">Document ID: {id}</p>
    </div>
  );
};
