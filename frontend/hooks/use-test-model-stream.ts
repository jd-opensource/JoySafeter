'use client'

import { useCallback, useRef, useState } from 'react'

import { apiStream } from '@/lib/api-client'
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
      if (!reader) throw new Error('No response body')

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
          let data: any
          try {
            data = JSON.parse(dataStr)
          } catch {
            continue
          }

          if (eventType === 'token') {
            setState((prev) => ({ ...prev, output: prev.output + (data.token ?? '') }))
          } else if (eventType === 'metrics') {
            setState((prev) => ({ ...prev, metrics: data as TestModelStreamMetrics }))
          } else if (eventType === 'error') {
            setState((prev) => ({ ...prev, error: data.error ?? 'Unknown error', isStreaming: false }))
            return
          } else if (eventType === 'done') {
            // handled below
          }
        }
      }
    } catch (err: any) {
      if (err?.name === 'AbortError') return
      setState((prev) => ({ ...prev, error: err?.message ?? 'Request failed', isStreaming: false }))
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
