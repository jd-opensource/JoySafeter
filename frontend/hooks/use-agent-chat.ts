'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { useChatMessage, threadKeys } from '@/hooks/queries/threads'
import { useExecutionStream } from '@/hooks/use-execution-stream'
import { TERMINAL_EXECUTION_STATUSES } from '@/types/executions'
import type { ThreadMessage } from '@/types/thread'

interface UseAgentChatOptions {
  threadId: string
  workspaceId: string
}

interface UseAgentChatResult {
  sendMessage: (message: string) => Promise<void>
  executionId: string | null
  executionStatus: string | null
  isSending: boolean
  isExecuting: boolean
  viewExecution: (executionId: string) => void
}

export function useAgentChat({
  threadId,
  workspaceId,
}: UseAgentChatOptions): UseAgentChatResult {
  const queryClient = useQueryClient()
  const chatMutation = useChatMessage()

  const [executionId, setExecutionId] = useState<string | null>(null)

  const { status: wsStatus } = useExecutionStream({
    executionId: executionId || '',
    enabled: Boolean(executionId),
  })

  const isExecuting = Boolean(
    executionId &&
    wsStatus &&
    !TERMINAL_EXECUTION_STATUSES.includes(wsStatus as never),
  )

  // Refresh messages when execution completes
  const prevStatusRef = useRef<string | null>(null)
  useEffect(() => {
    const prev = prevStatusRef.current
    const curr = wsStatus
    prevStatusRef.current = curr

    if (
      prev &&
      !TERMINAL_EXECUTION_STATUSES.includes(prev as never) &&
      curr &&
      TERMINAL_EXECUTION_STATUSES.includes(curr as never) &&
      threadId
    ) {
      setTimeout(() => {
        queryClient.invalidateQueries({
          queryKey: threadKeys.messages(threadId, workspaceId),
        })
      }, 500)
    }
  }, [wsStatus, threadId, workspaceId, queryClient])

  const sendMessage = useCallback(
    async (message: string) => {
      if (!threadId || chatMutation.isPending) return

      // Optimistic update: insert user message immediately
      const optimisticMsg: ThreadMessage = {
        id: `optimistic-${Date.now()}`,
        thread_id: threadId,
        run_id: null,
        execution_id: null,
        role: 'user',
        content: { text: message },
        created_at: new Date().toISOString(),
      }
      queryClient.setQueryData<ThreadMessage[]>(
        threadKeys.messages(threadId, workspaceId),
        (old) => [...(old ?? []), optimisticMsg],
      )

      const res = await chatMutation.mutateAsync({
        threadId,
        workspaceId,
        message,
      })
      setExecutionId(res.execution_id)
    },
    [threadId, workspaceId, chatMutation, queryClient],
  )

  const viewExecution = useCallback((eid: string) => {
    setExecutionId(eid)
  }, [])

  return {
    sendMessage,
    executionId,
    executionStatus: wsStatus,
    isSending: chatMutation.isPending,
    isExecuting,
    viewExecution,
  }
}
