/**
 * useToolInvocation hook
 * Custom hook for managing tool invocations
 */

import { useCallback } from 'react';

import type { ToolInvocation } from '@/types/dynamic/tool';

/**
 * Hook for managing tool invocations
 */
export const useToolInvocation = () => {
  const formatToolParameters = useCallback((params: Record<string, unknown>) => {
    return Object.entries(params)
      .map(([key, value]) => `${key}: ${JSON.stringify(value)}`)
      .join(', ');
  }, []);

  const formatToolResult = useCallback((result: unknown) => {
    if (typeof result === 'string') {
      return result;
    }
    return JSON.stringify(result, null, 2);
  }, []);

  const getToolStatusColor = useCallback((status: string) => {
    switch (status) {
      case 'pending':
        return 'bg-yellow-100 text-yellow-800';
      case 'executing':
        return 'bg-blue-100 text-blue-800';
      case 'completed':
        return 'bg-green-100 text-green-800';
      case 'failed':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  }, []);

  const groupToolInvocations = useCallback(
    (invocations: ToolInvocation[]) => {
      return invocations.reduce(
        (acc, inv) => {
          const toolName = inv.toolName;
          if (!acc[toolName]) {
            acc[toolName] = [];
          }
          acc[toolName].push(inv);
          return acc;
        },
        {} as Record<string, ToolInvocation[]>
      );
    },
    []
  );

  return {
    formatToolParameters,
    formatToolResult,
    getToolStatusColor,
    groupToolInvocations,
  };
};
