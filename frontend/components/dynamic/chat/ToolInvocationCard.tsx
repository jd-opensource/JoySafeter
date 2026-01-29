/**
 * ToolInvocationCard component
 * Displays tool invocation information
 */

import React from 'react';

import type { ToolInvocation } from '@/types/dynamic/tool';

interface ToolInvocationCardProps {
  invocation: ToolInvocation;
}

export const ToolInvocationCard: React.FC<ToolInvocationCardProps> = ({
  invocation,
}) => {
  return (
    <div className="tool-invocation-card">
      <div className="tool-name">{invocation.toolName}</div>
      {invocation.description && (
        <p className="text-sm text-gray-600 mb-2">{invocation.description}</p>
      )}
      <div className="tool-status">{invocation.status}</div>
      {/*{invocation.result && (*/}
      {/*  <div className="mt-2 p-2 bg-white rounded text-sm">*/}
      {/*    <strong>Result:</strong> {JSON.stringify(invocation.result)}*/}
      {/*  </div>*/}
      {/*)}*/}
      {invocation.executionTime && (
        <div className="text-xs text-gray-500 mt-1">
          Execution time: {invocation.executionTime}ms
        </div>
      )}
    </div>
  );
};

ToolInvocationCard.displayName = 'ToolInvocationCard';
