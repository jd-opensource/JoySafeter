'use client'

import { useCallback, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { threadService } from '@/services/threadService'
import { apiUpload } from '@/lib/api-client'
import { threadEventKeys } from './use-thread-events'
import type { ChatAttachment, ThreadEvent } from '@/types/thread'

export function useChatSend(threadId: string, workspaceId: string) {
  const queryClient = useQueryClient()
  const [isSending, setIsSending] = useState(false)
  const [executionId, setExecutionId] = useState<string | null>(null)

  const send = useCallback(
    async (message: string, files: File[] = []) => {
      if (!threadId || isSending) return null
      setIsSending(true)

      try {
        const attachments: ChatAttachment[] = []
        for (const file of files) {
          const result = await apiUpload<{
            filename: string
            path: string
            size: number
          }>('files/upload', file)
          attachments.push({
            filename: result.filename,
            storage_ref: result.path,
            mime_type: file.type || 'application/octet-stream',
            size_bytes: result.size,
          })
        }

        const optimisticEvent: ThreadEvent = {
          id: `optimistic-${Date.now()}`,
          run_id: '',
          execution_id: '',
          sequence_no: -1,
          event_type: 'user_message',
          payload: {
            text: message,
            ...(attachments.length ? { attachments } : {}),
          },
          execution_status: 'running',
          created_at: new Date().toISOString(),
        }
        queryClient.setQueryData(
          threadEventKeys.events(threadId, workspaceId),
          (
            old: { events: ThreadEvent[]; total: number } | undefined,
          ) => ({
            events: [...(old?.events ?? []), optimisticEvent],
            total: (old?.total ?? 0) + 1,
          }),
        )

        const res = await threadService.sendChat(
          threadId,
          workspaceId,
          message,
          attachments,
        )
        setExecutionId(res.execution_id)
        return res
      } finally {
        setIsSending(false)
      }
    },
    [threadId, workspaceId, isSending, queryClient],
  )

  return { send, isSending, executionId }
}
