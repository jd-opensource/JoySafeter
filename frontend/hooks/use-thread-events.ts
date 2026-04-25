'use client'

import { useQuery } from '@tanstack/react-query'

import { threadService } from '@/services/threadService'

export const threadEventKeys = {
  events: (threadId: string, workspaceId: string) =>
    ['thread-events', threadId, workspaceId] as const,
}

export function useThreadEvents(
  threadId: string,
  workspaceId: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: threadEventKeys.events(threadId, workspaceId),
    queryFn: () => threadService.listThreadEvents(threadId, workspaceId),
    enabled:
      Boolean(threadId) && Boolean(workspaceId) && options?.enabled !== false,
    refetchOnWindowFocus: false,
  })
}
