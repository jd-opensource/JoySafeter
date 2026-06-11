'use client'

import { useQuery } from '@tanstack/react-query'

import { threadService } from '@/services/threadService'

export const threadEventKeys = {
  events: (threadId: string, projectId: string) =>
    ['thread-events', threadId, projectId] as const,
}

export function useThreadEvents(
  threadId: string,
  projectId: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: threadEventKeys.events(threadId, projectId),
    queryFn: () => threadService.listThreadEvents(threadId),
    enabled: Boolean(threadId) && Boolean(projectId) && options?.enabled !== false,
    refetchOnWindowFocus: false,
  })
}
