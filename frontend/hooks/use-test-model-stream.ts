'use client'

import { useCallback, useRef, useState } from 'react'

import { ApiError, apiStream, createApiError, type ApiErrorPayload } from '@/lib/api-client'
import type {
  TestModelStreamMetrics,
  TestModelStreamRequest,
  TestModelStreamState,
} from '@/types/models'

export function useTestModelStream() {
  const [state, setState] = useState<TestModelStreamState>({
    output: '',
    metrics: null,
    error: null,
    isStreaming: false,
  })

  const abortRef = useRef<AbortController | null>(null)

  const run = useCallback(async (request: TestModelStreamRequest) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setState({ output: '', metrics: null, error: null, isStreaming: true })

    try {
      const response = await apiStream('models/test-output-stream', request, {
        signal: controller.signal,
      })

      const reader = response.body?.getReader()
      if (!reader) {
        throw createApiError(500, 'Invalid Stream Response', {
          code: 'MODEL_STREAM_RESPONSE_INVALID',
          message: 'No response body',
          data: null,
        })
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''

        for (const part of parts) {
          const eventMatch = part.match(/^event:\s*(\w+)\ndata:\s*(.+)$/s)
          if (!eventMatch) continue

          const [, eventType, dataStr] = eventMatch
          let data: unknown
          try {
            data = JSON.parse(dataStr)
          } catch {
            continue
          }

          if (eventType === 'token') {
            const tokenData = data as { token?: string }
            setState((prev) => ({ ...prev, output: prev.output + (tokenData.token ?? '') }))
          } else if (eventType === 'metrics') {
            setState((prev) => ({ ...prev, metrics: data as TestModelStreamMetrics }))
          } else if (eventType === 'error') {
            const errorPayload = data as ApiErrorPayload
            setState((prev) => ({
              ...prev,
              error: errorPayload,
              isStreaming: false,
            }))
            return
          } else if (eventType === 'done') {
            // handled below
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return
      const apiError =
        err instanceof ApiError
          ? err
          : err instanceof Error
            ? createApiError(0, 'Stream Error', {
                code: 'MODEL_STREAM_CLIENT_ERROR',
                message: err.message,
                data: null,
              })
            : createApiError(0, 'Stream Error', {
                code: 'MODEL_STREAM_CLIENT_ERROR',
                message: 'Request failed',
                data: null,
              })
      setState((prev) => ({
        ...prev,
        error: {
          code: apiError.code || 'MODEL_STREAM_CLIENT_ERROR',
          message: apiError.message,
          data: apiError.data,
        },
        isStreaming: false,
      }))
      return
    }

    setState((prev) => ({ ...prev, isStreaming: false }))
  }, [])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    setState((prev) => ({ ...prev, isStreaming: false }))
  }, [])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    setState({ output: '', metrics: null, error: null, isStreaming: false })
  }, [])

  return { ...state, run, stop, reset }
}
