'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import {
  ApiError,
  createApiError,
  extractErrorFromResponse,
  isUnauthorizedApiError,
  MANAGED_API_BASE,
  refreshAccessTokenOrRelogin,
} from '@/lib/api-client'
import { getCsrfToken } from '@/lib/auth/csrf'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { useProjectStore } from '@/stores/managed/project-store'
import type { SessionEvent } from '@/types/managed'

const NON_RECONNECT_ERROR_CODES = new Set([
  'HTTP_403',
  'FORBIDDEN',
  'PROJECT_ACCESS_DENIED',
  'JOYSAFETER_WRITE_REQUIRED',
  'JOYSAFETER_ADMIN_REQUIRED',
  'NOT_ORG_MEMBER',
])

export function useSessionStream(sessionId: string, enabled: boolean) {
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const currentProjectId = useProjectStore((state) => state.currentProjectId)
  const streamScope = `${sessionId}:${currentOrgId ?? ''}:${currentProjectId ?? ''}`
  const [eventState, setEventState] = useState<{ scope: string; events: SessionEvent[] }>({
    scope: '',
    events: [],
  })
  const [connectionState, setConnectionState] = useState<{ scope: string; connected: boolean }>({
    scope: '',
    connected: false,
  })
  const [errorState, setErrorState] = useState<{ scope: string; error: ApiError | null }>({
    scope: '',
    error: null,
  })
  const abortRef = useRef<AbortController | null>(null)
  const lastSeqRef = useRef<number>(0)
  const runIdRef = useRef(0)

  useEffect(() => {
    const runId = runIdRef.current + 1
    runIdRef.current = runId
    lastSeqRef.current = 0

    if (!enabled || !sessionId) {
      if (process.env.NODE_ENV !== 'production') {
        // eslint-disable-next-line no-console
        console.debug('[session-sse] disabled', { enabled, sessionId })
      }
      return
    }

    let cancelled = false
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    const isCurrentRun = () => !cancelled && runIdRef.current === runId

    const buildHeaders = (): Record<string, string> => {
      const headers: Record<string, string> = {}
      const csrfToken = getCsrfToken()
      if (csrfToken) {
        headers['X-CSRF-Token'] = csrfToken
      }
      if (currentOrgId) {
        headers['X-Org-Id'] = currentOrgId
      }
      if (currentProjectId) {
        headers['X-Project-Id'] = currentProjectId
      }
      return headers
    }

    const connect = async () => {
      if (!isCurrentRun()) return

      const controller = new AbortController()
      abortRef.current = controller

      try {
        const afterSeq = lastSeqRef.current
        const url = `${MANAGED_API_BASE}${apiResourcePath('sessions', sessionId, 'events', 'stream')}?after_seq=${afterSeq}`

        if (process.env.NODE_ENV !== 'production') {
          // eslint-disable-next-line no-console
          console.debug('[session-sse] connecting', url)
        }

        let didRefresh = false
        let resp = await fetch(url, {
          signal: controller.signal,
          headers: buildHeaders(),
          credentials: 'include',
        })
        if (resp.status === 401) {
          try {
            didRefresh = true
            await refreshAccessTokenOrRelogin()
            resp = await fetch(url, {
              signal: controller.signal,
              headers: buildHeaders(),
              credentials: 'include',
            })
          } catch (refreshError) {
            const apiError =
              refreshError instanceof ApiError
                ? refreshError
                : createApiError(0, 'SSE Refresh Error', {
                    code: 'SSE_REFRESH_FAILED',
                    message:
                      refreshError instanceof Error
                        ? refreshError.message
                        : 'Failed to refresh session stream authentication',
                    data: null,
                    source: 'auth',
                    user_action: 'relogin',
                  })
            if (!isCurrentRun()) return
            setErrorState({ scope: streamScope, error: apiError })
            if (!isUnauthorizedApiError(apiError)) {
              scheduleReconnect()
            }
            return
          }
        }
        if (!resp.ok || !resp.body) {
          const apiError = !resp.ok
            ? await extractErrorFromResponse(resp)
            : createApiError(0, 'SSE Stream Error', {
                code: 'SSE_STREAM_EMPTY',
                message: 'Session event stream returned no response body',
                data: null,
                source: 'api',
                retryable: true,
                user_action: 'retry',
              })
          if (!isCurrentRun()) return
          setErrorState({ scope: streamScope, error: apiError })
          if (process.env.NODE_ENV !== 'production') {
            // eslint-disable-next-line no-console
            console.debug('[session-sse] connect failed', {
              status: resp.status,
              statusText: resp.statusText,
              code: apiError.code,
              message: apiError.message,
              traceId: apiError.traceId,
              didRefresh,
            })
          }
          if (!isUnauthorizedApiError(apiError) && !NON_RECONNECT_ERROR_CODES.has(apiError.code)) {
            scheduleReconnect()
          }
          return
        }
        if (!isCurrentRun()) return
        setConnectionState({ scope: streamScope, connected: true })
        setErrorState({ scope: streamScope, error: null })
        if (process.env.NODE_ENV !== 'production') {
          // eslint-disable-next-line no-console
          console.debug('[session-sse] connected', url)
        }

        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let batch: SessionEvent[] = []
        let flushTimer: ReturnType<typeof setTimeout> | null = null
        let lagged = false

        const flush = () => {
          if (!isCurrentRun()) {
            batch = []
            if (flushTimer) clearTimeout(flushTimer)
            flushTimer = null
            return
          }
          if (batch.length > 0) {
            const toAdd = batch
            batch = []
            setEventState((prev) => {
              const eventKey = (event: SessionEvent) => {
                if (event.id) return event.id
                if (event.seq != null) return `${event.seq}:${event.type}`
                return `live:${event.type}:${JSON.stringify(event.content ?? event.usage ?? event.stop_reason ?? event.tool ?? '')}`
              }
              // On a session switch the accumulated bucket belongs to the
              // previous session; start fresh rather than appending to it.
              const base = prev.scope === streamScope ? prev.events : []
              const seen = new Set(base.map(eventKey))
              const next = [...base]
              for (const event of toAdd) {
                const key = eventKey(event)
                if (seen.has(key)) continue
                seen.add(key)
                next.push(event)
              }
              return { scope: streamScope, events: next }
            })
          }
          flushTimer = null
        }

        const processLine = (line: string) => {
          if (!line.startsWith('data:')) return
          const data = line.slice(5).trim()
          if (!data || data === '[DONE]') return
          try {
            const parsed = JSON.parse(data)
            if (parsed.lagged) {
              lagged = true
              return
            }
            const event = parsed as SessionEvent
            if (event.seq && event.seq > lastSeqRef.current) {
              lastSeqRef.current = event.seq
            }
            if (process.env.NODE_ENV !== 'production') {
              const source =
                (event as SessionEvent & { _sse_source?: string })._sse_source || 'unknown'
              // eslint-disable-next-line no-console
              console.debug('[session-sse]', source, event.type, event.seq)
            }
            batch.push(event)
          } catch {
            // ignore parse errors
          }
        }

        while (true) {
          if (!isCurrentRun()) break
          const { done, value } = await reader.read()
          if (done) {
            if (buffer.trim()) {
              processLine(buffer)
              buffer = ''
            }
            break
          }

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            processLine(line)
          }

          if (batch.length > 0 && !flushTimer) {
            flushTimer = setTimeout(flush, 50)
          }

          if (lagged) {
            flush()
            controller.abort()
            break
          }
        }
        flush()
        if (flushTimer) clearTimeout(flushTimer)

        if (!isCurrentRun()) return
        setConnectionState({ scope: streamScope, connected: false })
        scheduleReconnect()
      } catch (e) {
        if (isCurrentRun() && (e as Error).name !== 'AbortError') {
          setConnectionState({ scope: streamScope, connected: false })
          scheduleReconnect()
        }
      }
    }

    const scheduleReconnect = () => {
      if (!isCurrentRun()) return
      reconnectTimer = setTimeout(connect, 500)
    }

    connect()

    return () => {
      cancelled = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      abortRef.current?.abort()
      abortRef.current = null
    }
  }, [sessionId, enabled, currentOrgId, currentProjectId, streamScope])

  const clear = useCallback(() => {
    setEventState((prev) => ({ ...prev, events: [] }))
    lastSeqRef.current = 0
  }, [])

  return {
    events: enabled && eventState.scope === streamScope ? eventState.events : [],
    connected: enabled && connectionState.scope === streamScope ? connectionState.connected : false,
    error: enabled && errorState.scope === streamScope ? errorState.error : null,
    clear,
  }
}
