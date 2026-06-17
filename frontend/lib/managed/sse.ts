'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import type { SessionEvent } from '@/types/managed'
import { MANAGED_API_BASE } from '@/lib/api-client'
import { getCsrfToken } from '@/lib/auth/csrf'
import { useProjectStore } from '@/stores/managed/project-store'

export function useSessionStream(sessionId: string, enabled: boolean) {
  const [events, setEvents] = useState<SessionEvent[]>([])
  const [connected, setConnected] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const lastSeqRef = useRef<number>(0)

  useEffect(() => {
    if (!enabled || !sessionId) {
      if (process.env.NODE_ENV !== 'production') {
        // eslint-disable-next-line no-console
        console.debug('[session-sse] disabled', { enabled, sessionId })
      }
      return
    }

    let cancelled = false
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    const connect = async () => {
      if (cancelled) return

      const controller = new AbortController()
      abortRef.current = controller

      try {
        const afterSeq = lastSeqRef.current
        const url = `${MANAGED_API_BASE}/sessions/${sessionId}/events/stream?after_seq=${afterSeq}`

        if (process.env.NODE_ENV !== 'production') {
          // eslint-disable-next-line no-console
          console.debug('[session-sse] connecting', url)
        }

        const headers: Record<string, string> = {}
        const csrfToken = getCsrfToken()
        if (csrfToken) {
          headers['X-CSRF-Token'] = csrfToken
        }
        const { currentProjectId, currentOrgId } = useProjectStore.getState()
        if (currentOrgId) {
          headers['X-Org-Id'] = currentOrgId
        }
        if (currentProjectId) {
          headers['X-Project-Id'] = currentProjectId
        }

        const resp = await fetch(url, {
          signal: controller.signal,
          headers,
          credentials: 'include',
        })
        if (!resp.ok || !resp.body) {
          if (process.env.NODE_ENV !== 'production') {
            // eslint-disable-next-line no-console
            console.debug('[session-sse] connect failed', resp.status, resp.statusText)
          }
          scheduleReconnect()
          return
        }
        setConnected(true)
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
          if (batch.length > 0) {
            const toAdd = batch
            batch = []
            setEvents((prev) => {
              const eventKey = (event: SessionEvent) => {
                if (event.id) return event.id
                if (event.seq != null) return `${event.seq}:${event.type}`
                return `live:${event.type}:${JSON.stringify(event.content ?? event.usage ?? event.stop_reason ?? event.tool ?? '')}`
              }
              const seen = new Set(prev.map(eventKey))
              const next = [...prev]
              for (const event of toAdd) {
                const key = eventKey(event)
                if (seen.has(key)) continue
                seen.add(key)
                next.push(event)
              }
              return next
            })
          }
          flushTimer = null
        }

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            if (!line.startsWith('data:')) continue
            const data = line.slice(5).trim()
            if (!data || data === '[DONE]') continue
            try {
              const parsed = JSON.parse(data)
              if (parsed.lagged) {
                lagged = true
                continue
              }
              const event = parsed as SessionEvent
              if (event.seq && event.seq > lastSeqRef.current) {
                lastSeqRef.current = event.seq
              }
              if (process.env.NODE_ENV !== 'production') {
                const source = (event as SessionEvent & { _sse_source?: string })._sse_source || 'unknown'
                // eslint-disable-next-line no-console
                console.debug('[session-sse]', source, event.type, event.seq)
              }
              batch.push(event)
            } catch {
              // ignore parse errors
            }
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

        setConnected(false)
        scheduleReconnect()
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          setConnected(false)
          scheduleReconnect()
        }
      }
    }

    const scheduleReconnect = () => {
      if (cancelled) return
      reconnectTimer = setTimeout(connect, 500)
    }

    connect()

    return () => {
      cancelled = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      abortRef.current?.abort()
      abortRef.current = null
      setConnected(false)
    }
  }, [sessionId, enabled])

  const clear = useCallback(() => {
    setEvents([])
    lastSeqRef.current = 0
  }, [])

  return { events, connected, clear }
}
