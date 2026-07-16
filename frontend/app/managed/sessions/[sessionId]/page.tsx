'use client'

import React, { useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useMemo, useRef, useEffect, type ReactNode } from 'react'
import { i18n, useTranslation } from '@/lib/i18n'
import { Copy, Search, Package, Globe, KeyRound, Timer, MessageSquare, Clock, X, ArrowRight, Circle, ChevronRight, ChevronDown, Send, Archive, StopCircle, FileIcon, Plus, Trash2, GitBranch } from 'lucide-react'
import { managedGet, managedPost, managedDelete, managedPatch } from '@/lib/api-client'
import { shouldRetryManagedResourceError, toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
import {
  collapseRepeatedStatusEvents,
  getEventType,
  getLatestSessionStatusEvent,
  getMaxSeq,
  isRequiresActionIdle,
  mergeSessionEvents,
  sortSessionEvents,
} from '@/lib/managed/session-events'
import { useSessionStream } from '@/lib/managed/sse'
import type { Agent, Environment, Vault, VaultCredential, Session, SessionEvent, AgentTool, McpServer, SessionFileResource, SessionRepoResource, SessionResource, FileRecord } from '@/types/managed'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { StatusBadge, MonoId, ResourceErrorState, PageHeader } from '@/components/managed/shared'
import { EventList, EventDetail, EventFilter, EventTimeline } from '@/components/managed/session'
import { RelativeTime } from '@/components/managed/shared'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'

const TRANSCRIPT_TYPES = new Set([
  'user.message',
  'agent.message',
  'agent.mcp_tool_use',
  'agent.mcp_tool_result',
  'agent.tool_use',
  'agent.tool_result',
  'agent.custom_tool_use',
  'user.custom_tool_result',
  'user.tool_result',
  'agent.bg_task_started',
  'agent.bg_task_progress',
  'agent.bg_task_finished',
  'span.model_request_start',
  'span.model_request_end',
])

const TRANSCRIPT_DISPLAY_TYPES = new Set([
  'user.message',
  'agent.message',
  'agent.mcp_tool_use',
  'agent.tool_use',
  'agent.custom_tool_use',
  'user.custom_tool_result',
  'user.tool_result',
  'agent.bg_task_started',
  'agent.bg_task_progress',
  'agent.bg_task_finished',
  'span.model_request_start',
  'span.model_request_end',
])

const ALL_EVENT_TYPES = new Set([
  'agent.bg_task_finished',
  'agent.bg_task_progress',
  'agent.bg_task_started',
  'agent.custom_tool_use',
  'agent.error',
  'agent.mcp_tool_result',
  'agent.mcp_tool_use',
  'agent.message',
  'agent.thinking',
  'agent.thread_context_compacted',
  'agent.thread_message_received',
  'agent.thread_message_sent',
  'agent.tool_result',
  'agent.tool_use',
  'session.created',
  'session.error',
  'session.status_idle',
  'session.status_rescheduled',
  'session.status_running',
  'session.status_terminated',
  'session.thread_created',
  'session.thread_status_idle',
  'session.thread_status_running',
  'session.thread_status_terminated',
  'session.updated',
  'span.model_request_end',
  'span.model_request_start',
  'span.outcome_evaluation_end',
  'span.outcome_evaluation_ongoing',
  'span.outcome_evaluation_start',
  'user.custom_tool_result',
  'user.define_outcome',
  'user.interrupt',
  'user.message',
  'user.tool_confirmation',
  'user.tool_result',
])

const MIN_TRANSCRIPT_EVENTS = 30
const ENGINE_KIND_LABELS: Record<string, string> = {
  claude: 'Claude Code',
  claude_code: 'Claude Code',
  codex: 'Codex',
  native: 'Native',
}

export default function SessionDetailPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId: id } = React.use(params)
  const { t } = useTranslation()
  const router = useRouter()
  const [tab, setTab] = useState<'transcript' | 'debug'>('transcript')
  const [selectedEvent, setSelectedEvent] = useState<SessionEvent | null>(null)
  const [debugFilter, setDebugFilter] = useState<Set<string>>(ALL_EVENT_TYPES)
  const [searchText, setSearchText] = useState('')
  const [showSearch, setShowSearch] = useState(false)
  const [activeDrawer, setActiveDrawer] = useState<'agent' | 'env' | 'vault' | 'files' | 'repos' | null>(null)
  const [msgInput, setMsgInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [streamForced, setStreamForced] = useState(false)
  const queryClient = useQueryClient()
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const currentProjectId = useProjectStore((state) => state.currentProjectId)
  const projectReadOnly = useCurrentProjectReadOnly()
  const sessionScope = `${id ?? ''}:${currentOrgId ?? ''}:${currentProjectId ?? ''}`
  const sessionScopeRef = useRef(sessionScope)
  const actionRunRef = useRef(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  // Track whether the user is pinned to the bottom of the transcript. When true,
  // new events auto-scroll into view; when the user scrolls up to read history,
  // we stop yanking them back down.
  const stickToBottomRef = useRef(true)
  const { events: streamEvents, connected: sseConnected } = useSessionStream(stripIdPrefix(id || ''), !!id)

  const { data: session, isLoading, isError, error } = useQuery({
    queryKey: ['session', sessionScope],
    queryFn: () => managedGet<Session>(`/sessions/${stripIdPrefix(id)}`),
    enabled: !!id,
    retry: shouldRetryManagedResourceError,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      // Always poll when running — SSE may miss status change events
      if (status === 'running' || streamForced) return 3000
      return false
    },
  })

  const agentId = session?.agent?.agent_id || session?.agent?.id
  const { data: agentDetail } = useQuery({
    queryKey: ['agent', sessionScope, agentId],
    queryFn: () => managedGet<Agent>(`/agents/${stripIdPrefix(agentId!)}`),
    enabled: !!agentId && activeDrawer === 'agent',
  })

  const envId = session?.environment_id
  const { data: envDetail } = useQuery({
    queryKey: ['environment', sessionScope, envId],
    queryFn: () => managedGet<Environment>(`/environments/${stripIdPrefix(envId!)}`),
    enabled: !!envId,
  })

  const vaultId = session?.vault_ids?.[0]
  const { data: vaultDetail } = useQuery({
    queryKey: ['vault', sessionScope, vaultId],
    queryFn: () => managedGet<Vault>(`/vaults/${stripIdPrefix(vaultId!)}`),
    enabled: !!vaultId,
  })

  const { data: vaultCredentials } = useQuery({
    queryKey: ['vault-credentials', sessionScope, vaultId],
    queryFn: () => managedGet<{ data: VaultCredential[] }>(`/vaults/${stripIdPrefix(vaultId!)}/credentials?limit=100`),
    enabled: !!vaultId && activeDrawer === 'vault',
  })

  const { data: sessionResources } = useQuery({
    queryKey: ['session-resources', sessionScope],
    queryFn: () => managedGet<{ data: SessionResource[] }>(`/sessions/${stripIdPrefix(id)}/resources`),
    enabled: !!id,
  })
  const mountedFiles = useMemo(
    () => (sessionResources?.data || []).filter((r): r is SessionFileResource => r.type === 'file'),
    [sessionResources],
  )
  const mountedRepos = useMemo(
    () => (sessionResources?.data || []).filter((r): r is SessionRepoResource => r.type === 'github_repository'),
    [sessionResources],
  )

  const [loadedEvents, setLoadedEvents] = useState<SessionEvent[]>([])
  const [hasMoreEvents, setHasMoreEvents] = useState(true)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const eventsLoadedRef = useRef(false)

  useEffect(() => {
    if (sessionScopeRef.current === sessionScope) return
    sessionScopeRef.current = sessionScope
    actionRunRef.current += 1
    eventsLoadedRef.current = false
    setLoadedEvents([])
    setHasMoreEvents(true)
    setIsLoadingMore(false)
    setSelectedEvent(null)
    setActiveDrawer(null)
    setMsgInput('')
    setIsSending(false)
    setStreamForced(false)
  }, [sessionScope])

  const currentSessionScopeIsActive = useCallback(
    (scope = sessionScopeRef.current) => {
      const state = useProjectStore.getState()
      const currentScope = `${id ?? ''}:${state.currentOrgId ?? ''}:${state.currentProjectId ?? ''}`
      return sessionScopeRef.current === scope && currentScope === scope
    },
    [id],
  )

  const isCurrentAction = useCallback(
    (runId: number, scope: string) => {
      return actionRunRef.current === runId && currentSessionScopeIsActive(scope)
    },
    [currentSessionScopeIsActive],
  )

  const currentSessionDetail = useCallback(() => {
    if (!id) return null
    if (!currentSessionScopeIsActive()) return null
    const current = queryClient.getQueryData<Session>(['session', sessionScopeRef.current])
    return current?.id === id ? current : null
  }, [currentSessionScopeIsActive, id, queryClient])

  const loadEvents = useCallback(async (afterSeq?: number) => {
    if (!id) return
    const requestScope = sessionScopeRef.current
    if (!currentSessionScopeIsActive(requestScope)) return
    setIsLoadingMore(true)
    try {
      const params = new URLSearchParams({ limit: '100' })
      if (afterSeq != null) params.set('after_seq', String(afterSeq))
      const res = await managedGet<{ data: SessionEvent[]; has_more: boolean }>(`/sessions/${stripIdPrefix(id)}/events?${params.toString()}`)
      if (!currentSessionScopeIsActive(requestScope)) return
      const newEvents = Array.isArray(res) ? res : res.data
      const hasMore = Array.isArray(res) ? newEvents.length >= 100 : res.has_more
      setLoadedEvents((prev) =>
        sortSessionEvents(afterSeq != null ? [...prev, ...newEvents] : newEvents),
      )
      setHasMoreEvents(hasMore)
    } catch {
      // silently fail
    } finally {
      if (currentSessionScopeIsActive(requestScope)) {
        setIsLoadingMore(false)
      }
    }
  }, [currentSessionScopeIsActive, id])

  useEffect(() => {
    if (id && !eventsLoadedRef.current) {
      eventsLoadedRef.current = true
      loadEvents()
    }
  }, [id, loadEvents])

  const loadMoreEvents = useCallback(() => {
    if (!hasMoreEvents || isLoadingMore || loadedEvents.length === 0) return
    const lastSeq = getMaxSeq(loadedEvents)
    loadEvents(lastSeq)
  }, [hasMoreEvents, isLoadingMore, loadedEvents, loadEvents])

  const isRunning = session?.status === 'running'
  const isIdle = session?.status === 'idle'
  const isArchived = !!session?.archived_at
  const canEditMessage = !projectReadOnly && !isArchived && !isSending
  const canSendMessage = !projectReadOnly && isIdle && !isArchived && !isSending
  const wasRunningRef = useRef(false)

  // Update session status from live SSE events only. Initial SSE replay can contain
  // legacy/out-of-order status events, while the session query is DB-authoritative.
  useEffect(() => {
    if (!sseConnected || streamEvents.length === 0) return
    const sessionUpdatedAt = session?.updated_at ? new Date(session.updated_at).getTime() : 0
    const statusEvents = streamEvents.filter((e) => {
      const t = e.type || e.event_type || ''
      if (!t.startsWith('session.status_')) return false
      const eventCreatedAt = e.created_at ? new Date(e.created_at).getTime() : 0
      return !sessionUpdatedAt || !eventCreatedAt || eventCreatedAt >= sessionUpdatedAt
    })
    if (statusEvents.length === 0) return
    // Trigger API refetch instead of directly overriding status —
    // prevents stale/out-of-order SSE events from showing wrong status
    queryClient.invalidateQueries({ queryKey: ['session', sessionScope] })
  }, [streamEvents, sseConnected, session, id, queryClient])

  useEffect(() => {
    if (isRunning) wasRunningRef.current = true
    if (streamForced && wasRunningRef.current && !isRunning) {
      setStreamForced(false)
      wasRunningRef.current = false
      eventsLoadedRef.current = false; setLoadedEvents([]); loadEvents()
    }
  }, [isRunning, streamForced, id, queryClient])

  const handleSendMessage = async () => {
    const text = msgInput.trim()
    if (!text || !id || !canSendMessage) return
    if (!currentProjectAllowsWrite()) return
    const current = currentSessionDetail()
    if (!current || current.status !== 'idle' || current.archived_at) return
    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    const actionScope = sessionScopeRef.current
    if (!currentSessionScopeIsActive(actionScope)) return
    const sessionId = id
    setIsSending(true)
    setMsgInput('')
    setStreamForced(true)
    try {
      await managedPost(`/sessions/${stripIdPrefix(sessionId)}/events`, {
        events: [{ type: 'user.message', content: [{ type: 'text', text }] }],
      })
      if (!isCurrentAction(runId, actionScope)) return
      queryClient.invalidateQueries({ queryKey: ['session', actionScope] })
      eventsLoadedRef.current = false; setLoadedEvents([]); loadEvents()
    } catch (e) {
      if (!isCurrentAction(runId, actionScope)) return
      toastOperationError(t, e, 'common.operationFailed')
      setStreamForced(false)
    } finally {
      if (isCurrentAction(runId, actionScope)) {
        setIsSending(false)
      }
    }
  }

  // ---- Tool-confirmation (always_ask) approval ----
  const [approvingCallId, setApprovingCallId] = useState<string | null>(null)
  const [denyDraft, setDenyDraft] = useState<Record<string, string>>({})
  const sendToolConfirmation = useCallback(
    async (callId: string, approved: boolean, denyMessage?: string) => {
      if (!id || !callId) return
      if (!currentProjectAllowsWrite()) return
      const current = currentSessionDetail()
      if (!current || current.archived_at) return
      const runId = actionRunRef.current + 1
      actionRunRef.current = runId
      const actionScope = sessionScopeRef.current
      if (!currentSessionScopeIsActive(actionScope)) return
      const sessionId = id
      setApprovingCallId(callId)
      setStreamForced(true)
      try {
        const payload: Record<string, unknown> = {
          type: 'user.tool_confirmation',
          tool_use_id: callId,
          approved,
        }
        if (!approved && denyMessage) payload.deny_message = denyMessage
        await managedPost(`/sessions/${stripIdPrefix(sessionId)}/events`, {
          events: [payload],
        })
        if (!isCurrentAction(runId, actionScope)) return
        queryClient.invalidateQueries({ queryKey: ['session', actionScope] })
        eventsLoadedRef.current = false; setLoadedEvents([]); loadEvents()
      } catch (e) {
        if (!isCurrentAction(runId, actionScope)) return
        toastOperationError(t, e, 'common.operationFailed')
      } finally {
        if (isCurrentAction(runId, actionScope)) {
          setApprovingCallId(null)
        }
      }
    },
    [id, queryClient, loadEvents, t, isCurrentAction, currentSessionDetail],
  )

  const handleArchiveSession = async () => {
    if (!id) return
    if (!currentProjectAllowsWrite()) return
    const current = currentSessionDetail()
    if (!current || current.archived_at) return
    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    const actionScope = sessionScopeRef.current
    if (!currentSessionScopeIsActive(actionScope)) return
    const sessionId = id
    try {
      await managedPost(`/sessions/${stripIdPrefix(sessionId)}/archive`, {})
      if (!isCurrentAction(runId, actionScope)) return
      queryClient.invalidateQueries({ queryKey: ['session', actionScope] })
    } catch (e) {
      if (!isCurrentAction(runId, actionScope)) return
      toastOperationError(t, e, 'common.operationFailed')
    }
  }

  const handleStopSession = async () => {
    if (!id) return
    if (!currentProjectAllowsWrite()) return
    const current = currentSessionDetail()
    if (!current || current.status !== 'running' || current.archived_at) return
    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    const actionScope = sessionScopeRef.current
    if (!currentSessionScopeIsActive(actionScope)) return
    const sessionId = id
    try {
      await managedPost(`/sessions/${stripIdPrefix(sessionId)}/stop`, {})
      if (!isCurrentAction(runId, actionScope)) return
      queryClient.invalidateQueries({ queryKey: ['session', actionScope] })
      eventsLoadedRef.current = false; setLoadedEvents([]); loadEvents()
    } catch (e) {
      if (!isCurrentAction(runId, actionScope)) return
      toastOperationError(t, e, 'common.operationFailed')
    }
  }

  const currentSessionCanMutateResources = useCallback(() => {
    if (!currentProjectAllowsWrite()) return false
    const current = currentSessionDetail()
    return !!current && current.status === 'idle' && !current.archived_at
  }, [currentSessionDetail])

  const invalidateSessionResources = useCallback(
    (scope: string) => {
      if (!currentSessionScopeIsActive(scope)) return
      queryClient.invalidateQueries({ queryKey: ['session-resources', scope] })
    },
    [currentSessionScopeIsActive, queryClient],
  )

  const allEvents = useMemo(() => {
    return mergeSessionEvents(loadedEvents, streamEvents)
  }, [loadedEvents, streamEvents])

  // Pending tool-confirmation approvals (always_ask): control_request events
  // that have no matching user.tool_confirmation reply yet.
  const pendingApprovals = useMemo(() => {
    const confirmed = new Set<string>()
    for (const evt of allEvents) {
      const t = evt.type || evt.event_type || ''
      if (t === 'user.tool_confirmation') {
        const cid = (evt as { call_id?: string; tool_use_id?: string }).call_id
          || (evt as { tool_use_id?: string }).tool_use_id
        if (cid) confirmed.add(cid)
      }
    }
    const pending: Array<{ callId: string; tool: string; input: unknown; evt: SessionEvent }> = []
    for (const evt of allEvents) {
      const t = evt.type || evt.event_type || ''
      if (t !== 'agent.tool_use') continue
      const e = evt as SessionEvent & { is_control_request?: boolean; _call_id?: string }
      if (!e.is_control_request) continue
      const cid = e._call_id || (evt as { call_id?: string }).call_id || ''
      if (!cid || confirmed.has(cid)) continue
      pending.push({
        callId: cid,
        tool: (evt.name as string) || (evt.tool as string) || 'tool',
        input: (evt as { input?: unknown }).input,
        evt,
      })
    }
    return pending
  }, [allEvents])

  const displayStatus = useMemo(() => {
    if (isArchived) return 'archived'
    const currentStatus = session?.status || 'idle'

    // DB status is authoritative — only override for requires_action
    if (currentStatus === 'idle') {
      const latestStatusEvent = getLatestSessionStatusEvent(allEvents)
      if (latestStatusEvent && isRequiresActionIdle(latestStatusEvent)) return 'running'
    }

    return currentStatus
  }, [allEvents, isArchived, session?.status])

  const availableTypes = useMemo(() => {
    const types = new Set<string>()
    for (const e of allEvents) {
      const t = e.type || e.event_type || ''
      if (t) types.add(t)
    }
    return Array.from(types).sort()
  }, [allEvents])

  const filteredEvents = useMemo(() => {
    let events = allEvents

    if (tab === 'transcript') {
      events = events.filter((e) => TRANSCRIPT_TYPES.has(e.type || e.event_type || ''))
      // Hide stdio-protocol noise that the approval banner already covers:
      // - claude's --permission-prompt-tool emits an extra agent.tool_use
      //   with is_control_request:true alongside the real LLM tool_use
      //   (same name + args, no real tool_result), making it look like the
      //   tool ran twice.
      // - user.tool_confirmation is just the protocol ack of the approval
      //   button; the banner already represents the UX.
      events = events.filter((e) => {
        const t = e.type || e.event_type || ''
        if (t === 'user.tool_confirmation') return false
        if (t !== 'agent.tool_use') return true
        return !(e as { is_control_request?: boolean }).is_control_request
      })
    } else {
      events = events.filter((e) => debugFilter.has(e.type || e.event_type || ''))
    }

    if (searchText) {
      const lower = searchText.toLowerCase()
      events = events.filter((e) => {
        const full = JSON.stringify(e).toLowerCase()
        return full.includes(lower) || (e.type || e.event_type || '').includes(lower)
      })
    }

    // Debug mode: keep agent.message deltas raw, dedup tool events by call_id, pair tool_use -> tool_result
    if (tab === 'debug') {
      // Step 1: merge consecutive thinking deltas
      const step1: typeof events = []
      const extractDbgText = (e: SessionEvent): string => {
        if (Array.isArray(e.content)) return e.content.map((b) => b.text || '').join('')
        if (typeof e.content === 'string') return e.content
        return ''
      }
      for (const evt of events) {
        const t = evt.type || evt.event_type || ''
        const prev = step1[step1.length - 1]
        const prevType = prev ? (prev.type || prev.event_type || '') : ''
        if (t === 'agent.thinking' && prevType === t) {
          const combined = extractDbgText(prev) + extractDbgText(evt)
          step1[step1.length - 1] = { ...prev, content: [{ type: 'text', text: combined }] }
          continue
        }
        step1.push(evt)
      }

      // Step 2: collect tool_results by call_id for pairing
      const resultsByCallId = new Map<string, SessionEvent>()
      const seenResultCallIds = new Set<string>()
      for (const evt of step1) {
        const t = evt.type || evt.event_type || ''
        const callId = evt._call_id || evt.call_id || evt.tool_use_id || ''
        if ((t === 'agent.tool_result' || t === 'agent.mcp_tool_result') && callId && !seenResultCallIds.has(callId)) {
          seenResultCallIds.add(callId)
          resultsByCallId.set(callId, evt)
        }
      }

      // Step 3: build output -- dedup tool_use by call_id, insert matching result right after
      const debugMerged: typeof events = []
      const seenUseCallIds = new Set<string>()
      for (const evt of step1) {
        const t = evt.type || evt.event_type || ''

        // Skip tool_results -- they'll be inserted after matching tool_use
        if (t === 'agent.tool_result' || t === 'agent.mcp_tool_result') continue

        // Dedup tool_use by call_id and pair with result
        const useCallId = evt._call_id || evt.call_id || ''
        if ((t === 'agent.tool_use' || t === 'agent.mcp_tool_use') && useCallId) {
          if (seenUseCallIds.has(useCallId)) continue
          seenUseCallIds.add(useCallId)
          debugMerged.push(evt)
          const result = resultsByCallId.get(useCallId)
          if (result) {
            debugMerged.push(result)
            resultsByCallId.delete(useCallId)
          }
          continue
        }

        debugMerged.push(evt)
      }

      // Append unmatched results
      for (const result of resultsByCallId.values()) {
        debugMerged.push(result)
      }

      return collapseRepeatedStatusEvents(debugMerged)
    }

    // Transcript mode only: merge events for display
    if (tab !== 'transcript') {
      return events
    }

    // 1. Consecutive agent.message / agent.thinking -> combine text
    // 2. tool_result -> fold into matching tool_use by call_id, compute duration
    // 3. span.model_request_end -> attach usage (tokens) to preceding agent/tool row
    const TOOL_USE_TYPES_SET = new Set(['agent.tool_use', 'agent.mcp_tool_use', 'agent.custom_tool_use'])
    const TOOL_RESULT_TYPES_SET = new Set(['agent.tool_result', 'agent.mcp_tool_result', 'user.tool_result', 'user.custom_tool_result'])
    const merged: typeof events = []
    const extractText = (e: SessionEvent): string => {
      if (Array.isArray(e.content)) return e.content.map((b) => b.text || '').join('')
      if (typeof e.content === 'string') return e.content
      return ''
    }
    let toolUseStartTime = 0
    for (const evt of events) {
      const t = evt.type || evt.event_type || ''
      const prev = merged[merged.length - 1]
      const prevType = prev ? (prev.type || prev.event_type || '') : ''

      // Merge consecutive agent.message or agent.thinking
      if ((t === 'agent.message' || t === 'agent.thinking') && prevType === t) {
        const combined = extractText(prev) + extractText(evt)
        merged[merged.length - 1] = {
          ...prev,
          content: [{ type: 'text', text: combined }],
        }
        continue
      }

      // Fold tool_result into matching tool_use by call_id — compute duration
      if (TOOL_RESULT_TYPES_SET.has(t)) {
        const resultCallId = evt._call_id || evt.call_id || evt.tool_use_id || ''
        if (resultCallId) {
          for (let j = merged.length - 1; j >= 0; j--) {
            const candidate = merged[j]
            const candidateType = candidate.type || candidate.event_type || ''
            if (!TOOL_USE_TYPES_SET.has(candidateType)) continue
            const useCallId = candidate._call_id || candidate.call_id || ''
            if (useCallId === resultCallId) {
              let durationMs = candidate.duration_ms ?? 0
              if (candidate.created_at && evt.created_at) {
                const start = new Date(candidate.created_at).getTime()
                const end = new Date(evt.created_at).getTime()
                if (!isNaN(start) && !isNaN(end)) {
                  durationMs = end - start
                }
              }
              merged[j] = { ...candidate, is_error: candidate.is_error || evt.is_error || false, duration_ms: durationMs }
              break
            }
          }
        }
        continue
      }

      // span.model_request_end -> attach usage to preceding agent message only (not tool rows)
      if (t === 'span.model_request_end' && prev) {
        const usage = evt.usage
        if (usage && !TOOL_USE_TYPES_SET.has(prevType)) {
          merged[merged.length - 1] = {
            ...prev,
            usage,
            input_tokens: usage.input_tokens,
            output_tokens: usage.output_tokens,
          }
        }
        continue
      }

      // Skip orphan tool_result
      if (TOOL_RESULT_TYPES_SET.has(t)) continue
      // Skip model_request_start (not displayed)
      if (t === 'span.model_request_start') continue

      // Track tool_use start time for duration calculation
      if (TOOL_USE_TYPES_SET.has(t) && evt.created_at) {
        toolUseStartTime = new Date(evt.created_at).getTime()
      }

      if (TRANSCRIPT_DISPLAY_TYPES.has(t)) {
        merged.push(evt)
      }
    }

    return merged
  }, [allEvents, tab, debugFilter, searchText])

  useEffect(() => {
    // Skip auto-loading more events when SSE is connected — SSE pushes live events
    if (sseConnected) return
    if (tab !== 'transcript' || searchText || !hasMoreEvents || isLoadingMore || loadedEvents.length === 0) return

    if (filteredEvents.length < MIN_TRANSCRIPT_EVENTS) {
      loadMoreEvents()
    }
  }, [tab, searchText, hasMoreEvents, isLoadingMore, loadedEvents.length, filteredEvents.length, loadMoreEvents, sseConnected])

  // Auto-scroll to the newest event when the transcript grows, but only while
  // the user is pinned to the bottom (stickToBottomRef). Scrolling up to read
  // history flips the flag off in the container's onScroll handler.
  useEffect(() => {
    const el = scrollContainerRef.current
    if (!el) return
    if (!stickToBottomRef.current) return
    el.scrollTop = el.scrollHeight
  }, [filteredEvents.length])

  // Runtime duration — sum of each "running → idle" active period, not wall-clock.
  // Using allEvents (already loaded) so we exclude all idle gaps between tasks.
  // Fallback to stats.duration_seconds if events aren't loaded yet.
  const runtimeSec = useMemo(() => {
    // Last event timestamp — used to close an unterminated "running" period
    // (e.g. a task that timed out / was reaped and never emitted status_idle).
    let lastEventMs = 0
    for (const e of allEvents) {
      const ts = e.created_at ? new Date(e.created_at).getTime() : 0
      if (ts > lastEventMs) lastEventMs = ts
    }
    const statusEvts = allEvents.filter((e) => {
      const t2 = e.type || e.event_type || ''
      return t2 === 'session.status_running' || t2 === 'session.status_idle'
    })
    if (statusEvts.length >= 2) {
      let total = 0
      let runningAt: number | null = null
      for (const evt of statusEvts) {
        const t2 = evt.type || evt.event_type || ''
        const ts = evt.created_at ? new Date(evt.created_at).getTime() : null
        if (!ts) continue
        if (t2 === 'session.status_running') {
          runningAt = ts
        } else if (t2 === 'session.status_idle' && runningAt !== null) {
          total += (ts - runningAt) / 1000
          runningAt = null
        }
      }
      // Unterminated running period: still running → count to now; otherwise
      // (timed out / reaped without a closing idle) → count to last activity.
      if (runningAt !== null) {
        const endMs = session?.status === 'running'
          ? Date.now()
          : Math.max(lastEventMs, runningAt)
        total += (endMs - runningAt) / 1000
      }
      if (total > 0) return Math.round(total)
    }
    const statsDur = session?.stats?.duration_seconds ?? (session?.stats?.duration_ms ? session.stats.duration_ms / 1000 : 0)
    return statsDur > 0 ? Math.round(statsDur) : 0
  }, [allEvents, session?.stats, session?.status])

  if (isError) {
    return (
      <ResourceErrorState
        error={error}
        resource="session"
        backLabel={t('managed.sessions.backToSessions')}
        onBack={() => router.push('/managed/sessions')}
      />
    )
  }

  if (isLoading || !session) {
    return <div className="text-muted-foreground p-8">{t('common.loading')}</div>
  }

  const sessionStart = session.created_at

  // Build metadata items
  const metaItems: { icon: ReactNode; label: ReactNode; tooltip?: string; onClick?: () => void }[] = []
  if (session.agent) {
    metaItems.push({
      icon: <Package className="w-3.5 h-3.5" />,
      label: session.agent.name,
      tooltip: session.agent.name,
      onClick: () => setActiveDrawer('agent'),
    })
  }
  if (session.environment_id) {
    metaItems.push({
      icon: <Globe className="w-3.5 h-3.5" />,
      label: envDetail?.name || stripIdPrefix(session.environment_id).slice(0, 12),
      tooltip: envDetail?.name || session.environment_id,
      onClick: () => setActiveDrawer('env'),
    })
  }
  if (session.vault_ids && session.vault_ids.length > 0) {
    metaItems.push({
      icon: <KeyRound className="w-3.5 h-3.5" />,
      label: vaultDetail?.name || (session.vault_ids.length > 1 ? `${session.vault_ids.length} vaults` : stripIdPrefix(session.vault_ids[0]).slice(0, 12)),
      tooltip: vaultDetail?.name || session.vault_ids[0],
      onClick: () => setActiveDrawer('vault'),
    })
  }
  // Duration
  const durationSec = session.stats?.duration_seconds ?? (session.stats?.duration_ms ? session.stats.duration_ms / 1000 : 0)
  if (durationSec > 0) {
    const m = Math.floor(durationSec / 60)
    const s = Math.round(durationSec % 60)
    metaItems.push({
      icon: <Timer className="w-3.5 h-3.5" />,
      label: m > 0 ? `${m}m ${s}s` : `${s}s`,
    })
  }
  // Token usage
  if (session.usage && (session.usage.input_tokens > 0 || session.usage.output_tokens > 0)) {
    const fmt = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
    metaItems.push({
      icon: <MessageSquare className="w-3.5 h-3.5" />,
      label: `${fmt(session.usage.input_tokens)}/${fmt(session.usage.output_tokens)}`,
    })
  }
  // Mounted files
  if (mountedFiles.length > 0) {
    metaItems.push({
      icon: <FileIcon className="w-3.5 h-3.5" />,
      label: `${mountedFiles.length} ${t('managed.sessions.create.resources').toLowerCase()}`,
      onClick: () => setActiveDrawer('files'),
    })
  }
  // Mounted repos
  if (mountedRepos.length > 0) {
    metaItems.push({
      icon: <GitBranch className="w-3.5 h-3.5" />,
      label: `${mountedRepos.length} ${t('managed.sessions.create.repositories').toLowerCase()}`,
      onClick: () => setActiveDrawer('repos'),
    })
  }
  // Runtime duration (computed via useMemo above the early returns) — sum of
  // active "running → idle" periods, excluding idle gaps between tasks.
  if (runtimeSec > 0) {
    const h = Math.floor(runtimeSec / 3600)
    const m = Math.floor((runtimeSec % 3600) / 60)
    const s = runtimeSec % 60
    const runtimeLabel = h > 0 ? `${h}h ${m}m` : m > 0 ? `${m}m ${s}s` : `${s}s`
    metaItems.push({
      icon: <Timer className="w-3.5 h-3.5" />,
      label: runtimeLabel,
      tooltip: t('managed.sessions.runtimeDuration'),
    })
  }
  // Created time
  metaItems.push({
    icon: <Clock className="w-3.5 h-3.5" />,
    label: formatRelativeTime(session.created_at),
  })

  const sessionDisplayName = formatSessionId(session.id)

  return (
    <div className="h-[calc(100vh-4rem)] flex flex-col">
      {/* Header */}
      <div className="shrink-0">
        <PageHeader
          title={sessionDisplayName}
          titleExtra={<StatusBadge status={displayStatus} />}
          breadcrumb={[
            { label: t('managed.sessions.title'), to: '/managed/sessions' },
            { label: sessionDisplayName },
          ]}
          action={(
            <div className="flex items-center gap-2">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm">
                    {t('managed.sessions.actions')}
                    <ChevronDown className="w-3.5 h-3.5 ml-1" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onSelect={handleStopSession}
                    disabled={projectReadOnly || !isRunning || isArchived}
                  >
                    <StopCircle className="w-3.5 h-3.5 mr-2" />
                    {t('managed.sessions.stopSession')}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onSelect={handleArchiveSession}
                    disabled={projectReadOnly || isArchived}
                  >
                    <Archive className="w-3.5 h-3.5 mr-2" />
                    {t('managed.sessions.archive')}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <Button
                size="sm"
                onClick={() => {
                  if (msgInput.trim() && canSendMessage) {
                    handleSendMessage()
                  } else {
                    inputRef.current?.focus()
                  }
                }}
                disabled={!canEditMessage}
              >
                <Send className="w-3.5 h-3.5 mr-1" />
                {t('managed.sessions.sendMessage')}
              </Button>
            </div>
          )}
        />

        {/* Metadata bar - own line */}
        <div className="-mt-3 mb-4 flex items-center gap-1 text-sm text-muted-foreground">
          {metaItems.map((item, i) => (
            <span key={i} className="contents">
              {i > 0 && <span className="mx-1.5">&middot;</span>}
              <button
                type="button"
                title={item.tooltip}
                className={`inline-flex items-center gap-1.5 ${item.onClick ? 'hover:text-foreground cursor-pointer' : 'cursor-default'} transition-colors`}
                onClick={item.onClick}
                disabled={!item.onClick}
              >
                {item.icon}
                <span>{item.label}</span>
              </button>
            </span>
          ))}
        </div>
      </div>

      {/* Tab bar + toolbar */}
      <div className="shrink-0 flex items-center justify-between border-b border-border pb-0 mb-0">
        <div className="flex items-center gap-4">
          <Tabs value={tab} onValueChange={(v) => setTab(v as 'transcript' | 'debug')}>
            <TabsList>
              <TabsTrigger value="transcript">{t('managed.sessions.tab.transcript')}</TabsTrigger>
              <TabsTrigger value="debug">{t('managed.sessions.tab.debug')}</TabsTrigger>
            </TabsList>
          </Tabs>

          <EventFilter selected={debugFilter} onChange={setDebugFilter} availableTypes={availableTypes} />

          <button
            type="button"
            className="text-muted-foreground hover:text-foreground transition-colors"
            onClick={() => setShowSearch(!showSearch)}
          >
            <Search className="w-4 h-4" />
          </button>
        </div>

        <div className="flex items-center gap-2 pb-1">
          {isRunning && (
            <Circle className="w-3 h-3 fill-red-500 text-red-500" />
          )}
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => navigator.clipboard.writeText(JSON.stringify(allEvents, null, 2))}
          >
            <Copy className="w-3 h-3 mr-1" />
            {t('managed.sessions.copyAll')}
          </Button>
        </div>
      </div>

      {/* Search bar */}
      {showSearch && (
        <div className="shrink-0 pt-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
            <Input
              id="session-search"
              autoFocus
              placeholder={t('managed.sessions.searchEvents')}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              className="pl-7 h-7 text-xs w-[240px]"
            />
          </div>
        </div>
      )}

      {/* Timeline */}
      <div className="shrink-0 mt-3">
        <EventTimeline events={filteredEvents} sessionStart={sessionStart} selectedId={selectedEvent?.id || null} onSelect={setSelectedEvent} />
      </div>

      {/* Content: event list + detail panel */}
      <div className="flex-1 flex overflow-hidden border border-border rounded-lg">
        <div ref={scrollContainerRef} className="flex-1 overflow-y-auto" onScroll={(e) => {
          const el = e.currentTarget
          const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
          // Pin to bottom only when the user is within 80px of it, so live events
          // keep following; scrolling up to read history releases the pin.
          stickToBottomRef.current = distanceFromBottom < 80
          if (distanceFromBottom < 100 && hasMoreEvents && !isLoadingMore) {
            loadMoreEvents()
          }
        }}>
          <EventList
            events={filteredEvents}
            sessionStart={sessionStart}
            selectedId={selectedEvent?.id || null}
            onSelect={setSelectedEvent}
            mode={tab}
          />
          {isLoadingMore && (
            <div className="flex justify-center py-3">
              <span className="text-xs text-muted-foreground">{t('common.loading')}</span>
            </div>
          )}
        </div>

        {selectedEvent && (
          <div className="w-[420px] shrink-0 overflow-hidden">
            <EventDetail
              event={selectedEvent}
              mode={tab}
              sessionStart={sessionStart}
              onClose={() => setSelectedEvent(null)}
            />
          </div>
        )}
      </div>

      {/* Tool-confirmation approvals (always_ask) */}
      {pendingApprovals.length > 0 && (
        <div className="shrink-0 border-t border-amber-300 bg-amber-50 dark:bg-amber-950/30 px-3 py-2 space-y-2">
          {pendingApprovals.map((p) => {
            const sending = approvingCallId === p.callId
            const previewText = (() => {
              try {
                const i = typeof p.input === 'string' ? JSON.parse(p.input) : p.input
                if (i && typeof i === 'object') {
                  const obj = i as Record<string, unknown>
                  if (typeof obj.command === 'string') return obj.command
                  if (typeof obj.file_path === 'string') return obj.file_path
                  if (typeof obj.url === 'string') return obj.url
                  return JSON.stringify(obj).slice(0, 200)
                }
              } catch {}
              return ''
            })()
            return (
              <div
                key={p.callId}
                className="flex items-start gap-3 rounded-md border border-amber-300 bg-white dark:bg-background p-2"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium text-amber-800 dark:text-amber-300">
                    {t('managed.sessions.events.approvalBannerTitle', { tool: p.tool })}
                  </div>
                  {previewText && (
                    <div className="text-xs text-muted-foreground font-mono truncate mt-1">
                      {previewText}
                    </div>
                  )}
                  <Input
                    className="mt-2 text-xs h-7"
                    placeholder={t('managed.sessions.events.approvalDenyPlaceholder')}
                    value={denyDraft[p.callId] || ''}
                    onChange={(e) =>
                      setDenyDraft((prev) => ({ ...prev, [p.callId]: e.target.value }))
                    }
                    disabled={projectReadOnly || sending}
                  />
                </div>
                <div className="flex flex-col gap-1 shrink-0">
                  <Button
                    size="sm"
                    className="h-7 px-3 bg-emerald-500 hover:bg-emerald-600 text-white"
                    disabled={projectReadOnly || sending}
                    onClick={() => sendToolConfirmation(p.callId, true)}
                  >
                    {sending
                      ? t('managed.sessions.events.approvalSending')
                      : t('managed.sessions.events.approvalApprove')}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 px-3"
                    disabled={projectReadOnly || sending}
                    onClick={() =>
                      sendToolConfirmation(p.callId, false, denyDraft[p.callId] || undefined)
                    }
                  >
                    {t('managed.sessions.events.approvalDeny')}
                  </Button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Message input */}
      <div className="shrink-0 border-t border-border px-1 py-3">
        <div className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2">
          <input
            ref={inputRef}
            className="flex-1 bg-transparent outline-none text-sm placeholder:text-muted-foreground"
            value={msgInput}
            onChange={(e) => setMsgInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage() } }}
            disabled={!canEditMessage}
            placeholder={
              isArchived
                ? t('managed.sessions.archivedReadOnly')
                : isRunning
                  ? t('managed.sessions.agentRunning')
                  : t('managed.sessions.sendPlaceholder')
            }
          />
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            onClick={handleSendMessage}
            disabled={!msgInput.trim() || !canSendMessage}
          >
            <Send className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {/* Drawers */}
      {activeDrawer === 'agent' && (
        <AgentDrawer
          session={session}
          agent={agentDetail || null}
          queryScope={sessionScope}
          onClose={() => setActiveDrawer(null)}
          onGoToAgent={() => {
            if (agentId) router.push(`/managed/agents/${agentId}`)
          }}
        />
      )}
      {activeDrawer === 'env' && envDetail && (
        <EnvDrawer
          env={envDetail}
          onClose={() => setActiveDrawer(null)}
          onGoToEnv={() => router.push('/managed/environments')}
        />
      )}
      {activeDrawer === 'vault' && vaultDetail && (
        <VaultDrawer
          vault={vaultDetail}
          credentials={vaultCredentials?.data || []}
          onClose={() => setActiveDrawer(null)}
          onGoToVault={() => router.push(`/managed/vaults/${vaultDetail.id}`)}
        />
      )}
      {activeDrawer === 'files' && (
        <FilesDrawer
          sessionId={stripIdPrefix(id)}
          operationScope={sessionScope}
          files={mountedFiles}
          isIdle={!projectReadOnly && isIdle && !isArchived}
          canMutate={currentSessionCanMutateResources}
          isScopeActive={currentSessionScopeIsActive}
          onClose={() => setActiveDrawer(null)}
          onChanged={() => invalidateSessionResources(sessionScope)}
        />
      )}
      {activeDrawer === 'repos' && (
        <ReposDrawer
          sessionId={stripIdPrefix(id)}
          operationScope={sessionScope}
          repos={mountedRepos}
          isIdle={!projectReadOnly && isIdle && !isArchived}
          canMutate={currentSessionCanMutateResources}
          isScopeActive={currentSessionScopeIsActive}
          onClose={() => setActiveDrawer(null)}
          onChanged={() => invalidateSessionResources(sessionScope)}
        />
      )}
    </div>
  )
}

interface AgentVersionEntry {
  version: number
  snapshot: Agent
  created_at: string
}

function AgentDrawer({
  session,
  agent,
  queryScope,
  onClose,
  onGoToAgent,
}: {
  session: Session
  agent: Agent | null
  queryScope: string
  onClose: () => void
  onGoToAgent: () => void
}) {
  const { t } = useTranslation()
  const [promptExpanded, setPromptExpanded] = useState(true)
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)
  const [versionDropdownOpen, setVersionDropdownOpen] = useState(false)

  const agentId = agent?.id || session.agent?.id
  const rawAgentId = agentId ? stripIdPrefix(agentId) : null

  const { data: versionsData } = useQuery({
    queryKey: ['agent-versions', queryScope, rawAgentId],
    queryFn: () => managedGet<{ data: AgentVersionEntry[] }>(`/agents/${rawAgentId}/versions`),
    enabled: !!rawAgentId,
  })

  const rawVersions = versionsData?.data || []
  const currentVersion = agent?.version || session.agent?.version

  const versions = useMemo(() => {
    if (!currentVersion) return rawVersions
    const snapshotMap = new Map(rawVersions.map((v) => [v.version, v]))
    const all: AgentVersionEntry[] = []
    for (let i = currentVersion; i >= 1; i--) {
      const existing = snapshotMap.get(i)
      if (existing) {
        all.push(existing)
      } else if (i === currentVersion && agent) {
        all.push({ version: i, snapshot: agent, created_at: agent.created_at || '' })
      } else {
        all.push({ version: i, snapshot: null as unknown as Agent, created_at: '' })
      }
    }
    return all
  }, [rawVersions, currentVersion, agent])

  const displayAgent = useMemo(() => {
    if (selectedVersion !== null && selectedVersion !== currentVersion) {
      const entry = versions.find((v) => v.version === selectedVersion)
      if (entry?.snapshot) return entry.snapshot
    }
    return agent
  }, [selectedVersion, currentVersion, versions, agent])

  const activeVersion = selectedVersion ?? currentVersion
  const agentName = displayAgent?.name || session.agent?.name || 'Agent'

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      <div className="relative w-[480px] max-w-full bg-background border-l border-border h-full overflow-y-auto shadow-xl">
        <Button variant="ghost" size="icon" className="absolute right-4 top-4 h-8 w-8 z-10" onClick={onClose}>
          <X className="w-4 h-4" />
        </Button>

        <div className="px-6 py-5 space-y-6">
          {/* Header */}
          <section>
            <h2 className="text-base font-semibold text-foreground">{agentName}</h2>
            <div className="text-xs text-muted-foreground mt-1 space-y-0.5">
              {displayAgent && <div className="font-mono"><MonoId id={displayAgent.id} truncate={false} /></div>}
              <button
                className="inline-flex items-center gap-1 text-primary hover:underline"
                onClick={onGoToAgent}
              >
                {t('managed.sessions.goToAgent')} <ArrowRight className="w-3 h-3" />
              </button>
            </div>
          </section>

          {/* Version selector */}
          <section>
            <div className="relative">
              <button
                type="button"
                className="w-full flex items-center justify-between border border-border rounded-lg px-3 py-2 text-sm text-foreground hover:bg-muted/50 transition-colors"
                onClick={() => setVersionDropdownOpen(!versionDropdownOpen)}
              >
                <span>{t('managed.sessions.version')}: v{activeVersion}</span>
                <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${versionDropdownOpen ? 'rotate-180' : ''}`} />
              </button>
              {versionDropdownOpen && versions.length > 0 && (
                <div className="absolute z-20 mt-1 w-full bg-background border border-border rounded-lg shadow-lg overflow-hidden">
                  {versions.map((v) => (
                    <button
                      key={v.version}
                      type="button"
                      className={`w-full text-left px-3 py-2 text-sm hover:bg-muted transition-colors ${v.version === activeVersion ? 'bg-muted font-medium' : ''}`}
                      onClick={() => {
                        setSelectedVersion(v.version)
                        setVersionDropdownOpen(false)
                      }}
                    >
                      v{v.version}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </section>

          {!displayAgent ? (
            <div className="text-sm text-muted-foreground">{t('managed.sessions.loadingAgent')}</div>
          ) : (
            <>
              {/* Engine */}
              <section>
                <h3 className="text-sm font-semibold text-foreground mb-1">{t('managed.sessions.engineKind')}</h3>
                <p className="text-sm text-muted-foreground font-mono">
                  {displayAgent.engine_kind
                    ? ENGINE_KIND_LABELS[displayAgent.engine_kind] || displayAgent.engine_kind
                    : '-'}
                </p>
              </section>

              {/* Model */}
              <section>
                <h3 className="text-sm font-semibold text-foreground mb-1">{t('managed.sessions.model')}</h3>
                <p className="text-sm text-muted-foreground font-mono">{displayAgent.model?.id || "-"}</p>
              </section>

              {/* System prompt */}
              {(displayAgent.system || displayAgent.system_prompt) && (
                <section>
                  <button
                    type="button"
                    className="flex items-center gap-1.5 text-sm font-semibold text-foreground mb-2"
                    onClick={() => setPromptExpanded(!promptExpanded)}
                  >
                    <ChevronRight className={`w-3.5 h-3.5 transition-transform ${promptExpanded ? 'rotate-90' : ''}`} />
                    {t('managed.sessions.systemPrompt')}
                  </button>
                  {promptExpanded && (
                    <pre className="bg-muted p-4 rounded-lg text-xs overflow-x-auto whitespace-pre-wrap font-mono max-h-[300px] overflow-y-auto leading-relaxed">
                      {displayAgent.system || displayAgent.system_prompt}
                    </pre>
                  )}
                </section>
              )}

              {/* MCPs and tools */}
              <section>
                <h3 className="text-sm font-semibold text-foreground mb-3">{t('managed.sessions.mcpsAndTools')}</h3>
                {displayAgent.tools && displayAgent.tools.length > 0 ? (
                  <div className="space-y-3">
                    {displayAgent.tools.map((tool, i) => (
                      <DrawerToolCard key={i} tool={tool} mcpServers={displayAgent.mcp_servers} />
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">{t('managed.sessions.noTools')}</p>
                )}
              </section>

              {/* Skills */}
              <section>
                <h3 className="text-sm font-semibold text-foreground mb-1">{t('managed.sessions.skillsLabel')}</h3>
                <p className="text-sm text-muted-foreground">
                  {displayAgent.skills && displayAgent.skills.length > 0
                    ? t('managed.sessions.skillsConfigured', { count: displayAgent.skills.length })
                    : t('managed.sessions.noSkills')}
                </p>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function DrawerToolCard({ tool, mcpServers }: { tool: AgentTool; mcpServers?: McpServer[] }) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)

  if (tool.type === 'agent_toolset_20260401') {
    const configs = tool.configs || []
    const defaultPolicy = tool.default_config?.permission_policy?.type || 'always_allow'
    return (
      <div className="border border-border rounded-lg p-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-md bg-muted flex items-center justify-center shrink-0">
            <Package className="w-4 h-4 text-muted-foreground" />
          </div>
          <div>
            <div className="text-sm font-medium">{t('managed.sessions.builtInTools')}</div>
            <div className="text-xs text-muted-foreground font-mono">agent_toolset_20260401</div>
          </div>
        </div>
        <div className="mt-2 flex items-center justify-between">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <ChevronRight className={`w-3.5 h-3.5 transition-transform ${expanded ? 'rotate-90' : ''}`} />
            {t('managed.sessions.toolPermissions')}
            {configs.length > 0 && (
              <Badge variant="outline" className="ml-1 text-[10px] px-1.5 py-0">{configs.length}</Badge>
            )}
          </button>
          <span className="text-xs text-muted-foreground">{formatPolicy(defaultPolicy, t)}</span>
        </div>
        {expanded && configs.length > 0 && (
          <div className="mt-2 ml-5 space-y-1 border-l border-border pl-3">
            {configs.map((cfg, j) => {
              const enabled = cfg.enabled !== false
              const effectivePolicy = cfg.permission_policy?.type || defaultPolicy
              const isInherited = !cfg.permission_policy
              return (
                <div key={j} className="flex items-center justify-between text-xs py-0.5">
                  <span className="flex items-center gap-2">
                    {enabled ? (
                      <span
                        className="inline-flex h-3.5 w-3.5 items-center justify-center rounded bg-emerald-500 text-white"
                        aria-label="enabled"
                      >
                        <svg className="h-2.5 w-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={4}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                      </span>
                    ) : (
                      <span
                        className="inline-flex h-3.5 w-3.5 items-center justify-center rounded border border-border bg-background"
                        aria-label="disabled"
                      />
                    )}
                    <span className={`font-mono ${enabled ? 'text-foreground' : 'text-muted-foreground line-through'}`}>
                      {cfg.name}
                    </span>
                  </span>
                  <span className="text-muted-foreground">
                    {formatPolicy(effectivePolicy, t)}
                    {isInherited && (
                      <span className="ml-1 text-[10px] opacity-60">({t('managed.policy.inherit')})</span>
                    )}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    )
  }

  if (tool.type === 'mcp_toolset') {
    const configs = tool.configs || []
    const server = mcpServers?.find((s) => s.name === tool.mcp_server_name)
    const defaultPolicy = tool.default_config?.permission_policy?.type || 'always_ask'
    return (
      <div className="border border-border rounded-lg p-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-md bg-muted flex items-center justify-center shrink-0">
            <Globe className="w-4 h-4 text-muted-foreground" />
          </div>
          <div>
            <div className="text-sm font-medium">{tool.mcp_server_name}</div>
            {server && <div className="text-xs text-muted-foreground font-mono">{server.url}</div>}
          </div>
        </div>
        {(configs.length > 0 || defaultPolicy) && (
          <div className="mt-2 flex items-center justify-between">
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <ChevronRight className={`w-3.5 h-3.5 transition-transform ${expanded ? 'rotate-90' : ''}`} />
              {t('managed.sessions.toolPermissions')}
              {configs.length > 0 && (
                <Badge variant="outline" className="ml-1 text-[10px] px-1.5 py-0">{configs.length}</Badge>
              )}
            </button>
            {defaultPolicy && <span className="text-xs text-muted-foreground">{formatPolicy(defaultPolicy, t)}</span>}
          </div>
        )}
        {expanded && configs.length > 0 && (
          <div className="mt-2 ml-5 space-y-1 border-l border-border pl-3">
            {configs.map((cfg, j) => {
              const enabled = cfg.enabled !== false
              const effectivePolicy = cfg.permission_policy?.type || defaultPolicy
              const isInherited = !cfg.permission_policy
              return (
                <div key={j} className="flex items-center justify-between text-xs py-0.5">
                  <span className="flex items-center gap-2">
                    {enabled ? (
                      <span
                        className="inline-flex h-3.5 w-3.5 items-center justify-center rounded bg-emerald-500 text-white"
                        aria-label="enabled"
                      >
                        <svg className="h-2.5 w-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={4}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                      </span>
                    ) : (
                      <span
                        className="inline-flex h-3.5 w-3.5 items-center justify-center rounded border border-border bg-background"
                        aria-label="disabled"
                      />
                    )}
                    <span className={`font-mono ${enabled ? 'text-foreground' : 'text-muted-foreground line-through'}`}>
                      {cfg.name}
                    </span>
                  </span>
                  <span className="text-muted-foreground">
                    {formatPolicy(effectivePolicy, t)}
                    {isInherited && (
                      <span className="ml-1 text-[10px] opacity-60">({t('managed.policy.inherit')})</span>
                    )}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    )
  }

  if (tool.type === 'custom') {
    return (
      <div className="border border-border rounded-lg p-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-md bg-muted flex items-center justify-center shrink-0">
            <Package className="w-4 h-4 text-muted-foreground" />
          </div>
          <div>
            <div className="text-sm font-medium">{tool.name}</div>
            <div className="text-xs text-muted-foreground">{tool.description}</div>
          </div>
        </div>
      </div>
    )
  }

  return null
}

function formatPolicy(policy: string, t: (key: string) => string): string {
  switch (policy) {
    case 'always_allow': return t('managed.policy.alwaysAllow')
    case 'always_ask': return t('managed.policy.alwaysAsk')
    case 'always_deny': return t('managed.policy.alwaysDeny')
    case 'ask': return t('managed.policy.ask')
    case 'inherit': return t('managed.policy.inherit')
    default: return policy.replace(/_/g, ' ')
  }
}

function EnvDrawer({
  env,
  onClose,
  onGoToEnv,
}: {
  env: Environment
  onClose: () => void
  onGoToEnv: () => void
}) {
  const { t } = useTranslation()
  const isArchived = !!env.archived_at
  const envType = env.config?.type || 'cloud'
  const networking = env.config?.networking
  const packages = env.config?.packages
  const hasPackages = packages && (
    (packages.apt?.length ?? 0) + (packages.pip?.length ?? 0) + (packages.npm?.length ?? 0) +
    (packages.cargo?.length ?? 0) + (packages.gem?.length ?? 0) + (packages.go?.length ?? 0) > 0
  )

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      <div className="relative w-[480px] max-w-full bg-background border-l border-border h-full overflow-y-auto shadow-xl">
        <Button variant="ghost" size="icon" className="absolute right-4 top-4 h-8 w-8 z-10" onClick={onClose}>
          <X className="w-4 h-4" />
        </Button>

        <div className="px-6 py-5 space-y-6">
          {/* Header */}
          <section>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-base font-semibold text-foreground">{env.name}</h2>
              <StatusBadge status={isArchived ? 'archived' : 'active'} />
              <Badge variant="outline" className="text-xs capitalize">{envType}</Badge>
            </div>
            {env.description && (
              <p className="text-sm text-muted-foreground mt-1">{env.description}</p>
            )}
            <div className="text-xs text-muted-foreground mt-1.5 space-y-0.5">
              <div className="font-mono"><MonoId id={env.id} truncate={false} /></div>
              <button
                className="inline-flex items-center gap-1 text-primary hover:underline"
                onClick={onGoToEnv}
              >
                {t('managed.sessions.goToEnv')} <ArrowRight className="w-3 h-3" />
              </button>
            </div>
          </section>

          {/* Overview */}
          <section>
            <h3 className="text-sm font-semibold text-foreground mb-3">{t('managed.sessions.overview')}</h3>
            <div className="space-y-2">
              <div className="flex items-center text-sm">
                <span className="w-28 text-muted-foreground shrink-0">{t('managed.sessions.scope')}</span>
                <span className="text-foreground">{t('managed.sessions.organization')}</span>
              </div>
              <div className="flex items-center text-sm">
                <span className="w-28 text-muted-foreground shrink-0">{t('managed.sessions.created')}</span>
                <span className="text-foreground">{formatRelativeTime(env.created_at)}</span>
              </div>
            </div>
          </section>

          {/* Networking */}
          <section>
            <h3 className="text-sm font-semibold text-foreground mb-1">{t('managed.sessions.networking')}</h3>
            <p className="text-xs text-muted-foreground mb-3">{t('managed.sessions.networkingDesc')}</p>
            <div className="space-y-2">
              <div className="flex items-center text-sm">
                <span className="w-28 text-muted-foreground shrink-0">{t('managed.sessions.type')}</span>
                <span className="text-foreground capitalize">{networking?.type || 'limited'}</span>
              </div>
              <div className="flex items-center text-sm">
                <span className="w-28 text-muted-foreground shrink-0">{t('managed.sessions.mcpAccess')}</span>
                <span className="text-foreground">{networking?.allow_mcp_servers ? t('managed.sessions.enabled') : t('managed.sessions.disabled')}</span>
              </div>
              <div className="flex items-center text-sm">
                <span className="w-28 text-muted-foreground shrink-0">{t('managed.sessions.packages')}</span>
                <span className="text-foreground">{networking?.allow_package_managers ? t('managed.sessions.enabled') : t('managed.sessions.disabled')}</span>
              </div>
              {networking?.allowed_hosts && networking.allowed_hosts.length > 0 && (
                <div className="flex items-start text-sm">
                  <span className="w-28 text-muted-foreground shrink-0 pt-0.5">{t('managed.sessions.hosts')}</span>
                  <div className="flex flex-wrap gap-1.5">
                    {networking.allowed_hosts.map((host) => (
                      <code key={host} className="bg-muted px-2 py-0.5 rounded text-xs font-mono">{host}</code>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </section>

          {/* Packages */}
          <section>
            <h3 className="text-sm font-semibold text-foreground mb-2">{t('managed.sessions.packages')}</h3>
            {hasPackages ? (
              <div className="space-y-2">
                {packages.apt && packages.apt.length > 0 && (
                  <div className="flex items-start text-sm">
                    <span className="w-28 text-muted-foreground shrink-0">apt</span>
                    <div className="flex flex-wrap gap-1.5">
                      {packages.apt.map((p) => <code key={p} className="bg-muted px-2 py-0.5 rounded text-xs font-mono">{p}</code>)}
                    </div>
                  </div>
                )}
                {packages.pip && packages.pip.length > 0 && (
                  <div className="flex items-start text-sm">
                    <span className="w-28 text-muted-foreground shrink-0">pip</span>
                    <div className="flex flex-wrap gap-1.5">
                      {packages.pip.map((p) => <code key={p} className="bg-muted px-2 py-0.5 rounded text-xs font-mono">{p}</code>)}
                    </div>
                  </div>
                )}
                {packages.npm && packages.npm.length > 0 && (
                  <div className="flex items-start text-sm">
                    <span className="w-28 text-muted-foreground shrink-0">npm</span>
                    <div className="flex flex-wrap gap-1.5">
                      {packages.npm.map((p) => <code key={p} className="bg-muted px-2 py-0.5 rounded text-xs font-mono">{p}</code>)}
                    </div>
                  </div>
                )}
                {packages.cargo && packages.cargo.length > 0 && (
                  <div className="flex items-start text-sm">
                    <span className="w-28 text-muted-foreground shrink-0">cargo</span>
                    <div className="flex flex-wrap gap-1.5">
                      {packages.cargo.map((p) => <code key={p} className="bg-muted px-2 py-0.5 rounded text-xs font-mono">{p}</code>)}
                    </div>
                  </div>
                )}
                {packages.gem && packages.gem.length > 0 && (
                  <div className="flex items-start text-sm">
                    <span className="w-28 text-muted-foreground shrink-0">gem</span>
                    <div className="flex flex-wrap gap-1.5">
                      {packages.gem.map((p) => <code key={p} className="bg-muted px-2 py-0.5 rounded text-xs font-mono">{p}</code>)}
                    </div>
                  </div>
                )}
                {packages.go && packages.go.length > 0 && (
                  <div className="flex items-start text-sm">
                    <span className="w-28 text-muted-foreground shrink-0">go</span>
                    <div className="flex flex-wrap gap-1.5">
                      {packages.go.map((p) => <code key={p} className="bg-muted px-2 py-0.5 rounded text-xs font-mono">{p}</code>)}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground italic">{t('managed.sessions.noneConfigured')}</p>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

function VaultDrawer({
  vault,
  credentials,
  onClose,
  onGoToVault,
}: {
  vault: Vault
  credentials: VaultCredential[]
  onClose: () => void
  onGoToVault: () => void
}) {
  const { t } = useTranslation()
  const isArchived = !!vault.archived_at
  const activeCreds = credentials.filter((c) => !c.archived_at)

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      <div className="relative w-[480px] max-w-full bg-background border-l border-border h-full overflow-y-auto shadow-xl">
        <div className="sticky top-0 bg-background border-b border-border px-6 py-4 flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold">{vault.name}</h2>
              <StatusBadge status={isArchived ? 'archived' : 'active'} />
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground mt-1">
              <span>{t('managed.sessions.created')} <RelativeTime date={vault.created_at} /></span>
              <span>&middot;</span>
              <MonoId id={vault.id} />
              <span>&middot;</span>
              <button
                className="inline-flex items-center gap-1 text-primary hover:underline"
                onClick={onGoToVault}
              >
                {t('managed.sessions.goToVault')} <ArrowRight className="w-3 h-3" />
              </button>
            </div>
          </div>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose}>
            <X className="w-4 h-4" />
          </Button>
        </div>

        <div className="px-6 py-5">
          <h3 className="text-sm font-semibold text-foreground">{t('managed.sessions.credentials')}</h3>
          <p className="text-xs text-muted-foreground mb-4">
            {t('managed.sessions.credentialsDesc')}
          </p>

          {activeCreds.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('managed.sessions.noCredentials')}</p>
          ) : (
            <div className="space-y-4">
              {activeCreds.map((cred) => (
                <div key={cred.id} className="border border-border rounded-lg p-4 space-y-1.5">
                  <div className="text-sm font-semibold text-foreground">{cred.name}</div>
                  <div className="text-xs text-muted-foreground font-mono">{cred.mcp_server_url}</div>
                  {cred.oauth_config?.expires_at && (
                    <div className="flex items-center text-xs text-muted-foreground">
                      <span className="w-16 shrink-0">{t('managed.sessions.expires')}</span>
                      <span>
                        {new Date(cred.oauth_config.expires_at).toLocaleDateString('en-US', {
                          month: 'short',
                          day: 'numeric',
                          year: 'numeric',
                          hour: 'numeric',
                          minute: '2-digit',
                        })}
                      </span>
                    </div>
                  )}
                  <div className="flex items-center text-xs text-muted-foreground">
                    <span className="w-16 shrink-0">ID</span>
                    <span className="font-mono">{cred.id}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function FilesDrawer({
  sessionId,
  operationScope,
  files,
  isIdle,
  canMutate,
  isScopeActive,
  onClose,
  onChanged,
}: {
  sessionId: string
  operationScope: string
  files: SessionFileResource[]
  isIdle: boolean
  canMutate: () => boolean
  isScopeActive: (scope: string) => boolean
  onClose: () => void
  onChanged: () => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [showAddDropdown, setShowAddDropdown] = useState(false)
  const operationScopeRef = useRef(operationScope)
  const mutationRunRef = useRef(0)

  useEffect(() => {
    if (operationScopeRef.current === operationScope) return
    operationScopeRef.current = operationScope
    mutationRunRef.current += 1
    setShowAddDropdown(false)
  }, [operationScope])

  useEffect(
    () => () => {
      mutationRunRef.current += 1
    },
    [],
  )

  const isCurrentMutation = (runId: number, scope: string) =>
    mutationRunRef.current === runId && operationScopeRef.current === scope && isScopeActive(scope)

  const nextMutation = () => {
    if (!isScopeActive(operationScopeRef.current)) return null
    const runId = mutationRunRef.current + 1
    mutationRunRef.current = runId
    return { runId, scope: operationScopeRef.current }
  }

  const toggleAddDropdown = () => {
    if (!canMutate()) {
      setShowAddDropdown(false)
      return
    }
    mutationRunRef.current += 1
    setShowAddDropdown((open) => !open)
  }

  const { data: allFilesResp } = useQuery({
    queryKey: ['files-for-add', operationScope],
    queryFn: () => managedGet<{ data: FileRecord[] }>('/files?limit=100'),
    enabled: showAddDropdown,
  })
  const allFiles = useMemo(() => {
    if (!allFilesResp) return []
    return allFilesResp.data || []
  }, [allFilesResp])

  const alreadyMountedIds = new Set(files.map((f) => f.file_id))
  const availableFiles = allFiles.filter((f) => !alreadyMountedIds.has(f.id))

  const addFileMutation = useMutation({
    mutationFn: ({
      file,
      sessionId,
      runId,
      scope,
    }: {
      file: FileRecord
      sessionId: string
      runId: number
      scope: string
    }) => {
      if (!isCurrentMutation(runId, scope)) return Promise.resolve(undefined)
      return managedPost(`/sessions/${sessionId}/resources`, {
        type: 'file',
        file_id: file.id,
        mount_path: `/workspace/${file.filename}`,
      })
    },
    onSuccess: (_data, { runId, scope }) => {
      if (!isCurrentMutation(runId, scope)) return
      onChanged()
      setShowAddDropdown(false)
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentMutation(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const removeFileMutation = useMutation({
    mutationFn: ({
      resourceId,
      sessionId,
      runId,
      scope,
    }: {
      resourceId: string
      sessionId: string
      runId: number
      scope: string
    }) => {
      if (!isCurrentMutation(runId, scope)) return Promise.resolve(undefined)
      return managedDelete(`/sessions/${sessionId}/resources/${resourceId}`)
    },
    onSuccess: (_data, { runId, scope }) => {
      if (!isCurrentMutation(runId, scope)) return
      onChanged()
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentMutation(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const handleAddFile = (file: FileRecord) => {
    if (!canMutate()) {
      setShowAddDropdown(false)
      return
    }
    const currentFiles =
      queryClient.getQueryData<{ data?: FileRecord[] }>([
        'files-for-add',
        operationScopeRef.current,
      ])?.data || []
    const currentFile = currentFiles.find((candidate) => candidate.id === file.id)
    if (!currentFile) return

    const currentResources = queryClient.getQueryData<{ data?: SessionResource[] }>([
      'session-resources',
      operationScopeRef.current,
    ])
    const currentMountedIds = new Set(
      (currentResources?.data || files)
        .filter((resource): resource is SessionFileResource => resource.type === 'file')
        .map((resource) => resource.file_id),
    )
    if (currentMountedIds.has(currentFile.id)) return

    const action = nextMutation()
    if (!action) return

    addFileMutation.mutate({
      file: currentFile,
      sessionId,
      ...action,
    })
  }

  const handleRemoveFile = (resourceId: string) => {
    if (!canMutate()) return

    const currentResources = queryClient.getQueryData<{ data?: SessionResource[] }>([
      'session-resources',
      operationScopeRef.current,
    ])
    const currentFileResource = (currentResources?.data || files)
      .filter((resource): resource is SessionFileResource => resource.type === 'file')
      .find((resource) => resource.id === resourceId)
    if (!currentFileResource) return

    const action = nextMutation()
    if (!action) return

    removeFileMutation.mutate({
      resourceId: currentFileResource.id,
      sessionId,
      ...action,
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      <div className="relative w-[480px] max-w-full bg-background border-l border-border h-full overflow-y-auto shadow-xl">
        <Button variant="ghost" size="icon" className="absolute right-4 top-4 h-8 w-8 z-10" onClick={onClose}>
          <X className="w-4 h-4" />
        </Button>

        <div className="px-6 py-5 space-y-6">
          <section>
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-foreground">{t('managed.sessions.mountedFiles')}</h2>
              {isIdle && (
                <div className="relative">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={toggleAddDropdown}
                  >
                    <Plus className="w-3.5 h-3.5 mr-1" />
                    {t('managed.sessions.addFile')}
                  </Button>
                  {showAddDropdown && (
                    <div className="absolute right-0 z-50 mt-1 w-64 rounded-md border border-border bg-background py-1 shadow-lg max-h-48 overflow-y-auto">
                      {availableFiles.length === 0 ? (
                        <div className="px-3 py-2 text-sm text-muted-foreground">
                          {t('managed.sessions.create.noFiles')}
                        </div>
                      ) : (
                        availableFiles.map((f) => (
                          <button
                            key={f.id}
                            type="button"
                            onClick={() => handleAddFile(f)}
                            className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-muted/50"
                          >
                            <FileIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                            <span className="truncate">{f.filename}</span>
                          </button>
                        ))
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {t('managed.sessions.create.resourcesDesc')}
            </p>
          </section>

          {files.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('managed.sessions.noMountedFiles')}</p>
          ) : (
            <div className="space-y-3">
              {files.map((f) => (
                <div key={f.id} className="border border-border rounded-lg p-3 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <FileIcon className="w-4 h-4 text-muted-foreground" />
                      <span className="text-sm font-medium font-mono">{f.file_id}</span>
                    </div>
                    {isIdle && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-destructive"
                        onClick={() => handleRemoveFile(f.id)}
                        disabled={removeFileMutation.isPending}
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </Button>
                    )}
                  </div>
                  <div className="flex items-center text-xs text-muted-foreground">
                    <span className="w-20 shrink-0">{t('managed.sessions.create.mountPath')}</span>
                    <code className="bg-muted px-1.5 py-0.5 rounded font-mono">{f.mount_path}</code>
                  </div>
                  <div className="flex items-center text-xs text-muted-foreground">
                    <span className="w-20 shrink-0">{t('managed.sessions.type')}</span>
                    <span>{f.access}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ReposDrawer({
  sessionId,
  operationScope,
  repos,
  isIdle,
  canMutate,
  isScopeActive,
  onClose,
  onChanged,
}: {
  sessionId: string
  operationScope: string
  repos: SessionRepoResource[]
  isIdle: boolean
  canMutate: () => boolean
  isScopeActive: (scope: string) => boolean
  onClose: () => void
  onChanged: () => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [tokenEdits, setTokenEdits] = useState<Record<string, string>>({})
  const tokenDraftVersionsRef = useRef<Record<string, number>>({})
  const operationScopeRef = useRef(operationScope)
  const mutationRunRef = useRef(0)

  useEffect(() => {
    if (operationScopeRef.current === operationScope) return
    operationScopeRef.current = operationScope
    mutationRunRef.current += 1
    tokenDraftVersionsRef.current = {}
    setTokenEdits({})
  }, [operationScope])

  useEffect(
    () => () => {
      mutationRunRef.current += 1
    },
    [],
  )

  const isCurrentMutation = (runId: number, scope: string) =>
    mutationRunRef.current === runId && operationScopeRef.current === scope && isScopeActive(scope)

  const nextMutation = () => {
    if (!isScopeActive(operationScopeRef.current)) return null
    const runId = mutationRunRef.current + 1
    mutationRunRef.current = runId
    return { runId, scope: operationScopeRef.current }
  }

  const updateTokenDraft = (resourceId: string, token: string) => {
    tokenDraftVersionsRef.current[resourceId] = (tokenDraftVersionsRef.current[resourceId] ?? 0) + 1
    setTokenEdits((prev) => ({ ...prev, [resourceId]: token }))
  }

  const rotateMutation = useMutation({
    mutationFn: ({
      resourceId,
      sessionId,
      token,
      runId,
      scope,
      draftVersion,
    }: {
      resourceId: string
      sessionId: string
      token: string
      draftVersion: number
      runId: number
      scope: string
    }) => {
      if (!isCurrentMutation(runId, scope)) return Promise.resolve(undefined)
      return managedPatch(`/sessions/${sessionId}/resources/${resourceId}`, {
        authorization_token: token,
      })
    },
    onSuccess: (_data, vars) => {
      if (!isCurrentMutation(vars.runId, vars.scope)) return
      onChanged()
      if ((tokenDraftVersionsRef.current[vars.resourceId] ?? 0) === vars.draftVersion) {
        setTokenEdits((prev) => {
          const next = { ...prev }
          delete next[vars.resourceId]
          return next
        })
      }
    },
    onError: (error, { draftVersion, resourceId, runId, scope }) => {
      if (!isCurrentMutation(runId, scope)) return
      if ((tokenDraftVersionsRef.current[resourceId] ?? 0) !== draftVersion) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const handleRotateToken = (repo: SessionRepoResource) => {
    const token = (tokenEdits[repo.id] ?? '').trim()
    if (!token) return
    if (!canMutate()) return

    const currentResources = queryClient.getQueryData<{ data?: SessionResource[] }>([
      'session-resources',
      operationScopeRef.current,
    ])
    const currentRepo = (currentResources?.data || repos)
      .filter((resource): resource is SessionRepoResource => resource.type === 'github_repository')
      .find((resource) => resource.id === repo.id)
    if (!currentRepo) return

    const action = nextMutation()
    if (!action) return

    rotateMutation.mutate({
      resourceId: currentRepo.id,
      sessionId,
      token,
      draftVersion: tokenDraftVersionsRef.current[currentRepo.id] ?? 0,
      ...action,
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      <div className="relative w-[480px] max-w-full bg-background border-l border-border h-full overflow-y-auto shadow-xl">
        <Button variant="ghost" size="icon" className="absolute right-4 top-4 h-8 w-8 z-10" onClick={onClose}>
          <X className="w-4 h-4" />
        </Button>

        <div className="px-6 py-5 space-y-6">
          <section>
            <h2 className="text-base font-semibold text-foreground">{t('managed.sessions.mountedRepos')}</h2>
            <p className="text-xs text-muted-foreground mt-1">{t('managed.sessions.create.repositoriesDesc')}</p>
          </section>

          {repos.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('managed.sessions.noMountedRepos')}</p>
          ) : (
            <div className="space-y-3">
              {repos.map((r) => (
                <div key={r.id} className="border border-border rounded-lg p-3 space-y-1.5">
                  <div className="flex items-center gap-2">
                    <GitBranch className="w-4 h-4 text-muted-foreground shrink-0" />
                    <span className="text-sm font-medium font-mono truncate">{r.url}</span>
                  </div>
                  {r.branch && (
                    <div className="flex items-center text-xs text-muted-foreground">
                      <span className="w-20 shrink-0">{t('managed.sessions.create.repoBranch')}</span>
                      <code className="bg-muted px-1.5 py-0.5 rounded font-mono">{r.branch}</code>
                    </div>
                  )}
                  {r.mount_path && (
                    <div className="flex items-center text-xs text-muted-foreground">
                      <span className="w-20 shrink-0">{t('managed.sessions.create.mountPath')}</span>
                      <code className="bg-muted px-1.5 py-0.5 rounded font-mono">{r.mount_path}</code>
                    </div>
                  )}
                  {isIdle && (
                    <div className="flex items-center gap-1.5 pt-1.5">
                      <Input
                        type="password"
                        autoComplete="new-password"
                        value={tokenEdits[r.id] ?? ''}
                        onChange={(e) => updateTokenDraft(r.id, e.target.value)}
                        className="h-7 text-xs font-mono"
                        placeholder={t('managed.sessions.rotateTokenPlaceholder')}
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        className="shrink-0"
                        disabled={!(tokenEdits[r.id] ?? '').trim() || rotateMutation.isPending}
                        onClick={() => handleRotateToken(r)}
                      >
                        {t('managed.sessions.rotateToken')}
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function formatRelativeTime(dateStr: string): string {
  const isZh = i18n.language?.startsWith('zh')
  const locale = isZh ? 'zh-CN' : 'en-US'
  return new Date(dateStr).toLocaleString(locale, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatSessionId(id: string): string {
  return id.startsWith('sess_') ? id : `sess_${stripIdPrefix(id)}`
}
