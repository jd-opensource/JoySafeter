'use client'

import React, { useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useMemo, useRef, useEffect, type ReactNode } from 'react'
import { i18n, useTranslation } from '@/lib/i18n'
import {
  Copy,
  Search,
  Package,
  Globe,
  KeyRound,
  Timer,
  MessageSquare,
  Clock,
  X,
  ArrowRight,
  Circle,
  ChevronRight,
  ChevronDown,
  Send,
  Archive,
  StopCircle,
  FileIcon,
  Folder,
  Download,
  Eye,
  Plus,
  Trash2,
  GitBranch,
  ShieldCheck,
  AlertTriangle,
} from 'lucide-react'
import {
  managedDelete,
  managedFetchResponse,
  managedGet,
  managedPatch,
  managedPost,
} from '@/lib/api-client'
import { apiResourceId, apiResourcePath, apiResourceSubpath } from '@/lib/managed/api-paths'
import { shouldRetryManagedResourceError, toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
import { generateUUID } from '@/lib/utils/uuid'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  managedScopeKey,
  type ManagedRequestScope,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import {
  collapseRepeatedStatusEvents,
  getEventType,
  getLatestSessionStatusEvent,
  getMaxSeq,
  getMinSeq,
  isRequiresActionIdle,
  mergeSessionEvents,
  sortSessionEvents,
} from '@/lib/managed/session-events'
import { useSessionStream } from '@/lib/managed/sse'
import {
  getCachedSessionEventState,
  setCachedSessionEventState,
} from '@/lib/managed/session-event-cache'
import type {
  Agent,
  Environment,
  Vault,
  VaultCredential,
  Session,
  SessionEvent,
  AgentTool,
  McpServer,
  SessionFileResource,
  SessionRepoResource,
  SessionResource,
  SessionSkillUsage,
  FileRecord,
  NetworkPolicyStatus,
} from '@/types/managed'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
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
  const [activeDrawer, setActiveDrawer] = useState<
    'agent' | 'env' | 'vault' | 'files' | 'repos' | null
  >(null)
  const [msgInput, setMsgInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [streamForced, setStreamForced] = useState(false)
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()
  const sessionScope = `${id ?? ''}:${managedScope.key}`
  const sessionScopeRef = useRef(sessionScope)
  const managedRequestScopeRef = useRef<ManagedRequestScope>(managedScope)
  const actionRunRef = useRef(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  // Track whether the user is pinned to the bottom of the transcript. When true,
  // new events auto-scroll into view; when the user scrolls up to read history,
  // we stop yanking them back down.
  const stickToBottomRef = useRef(true)
  const pendingPrependScrollHeightRef = useRef<number | null>(null)

  const openSessionFiles = useCallback(() => {
    setActiveDrawer('files')
  }, [])

  const {
    data: session,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['session', sessionScope],
    queryFn: () =>
      managedGet<Session>(apiResourcePath('sessions', id), managedRequestOptions(managedScope)),
    enabled: !!id && hasManagedRequestScope(managedScope),
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
    queryFn: () =>
      managedGet<Agent>(apiResourcePath('agents', agentId!), managedRequestOptions(managedScope)),
    enabled: !!agentId && activeDrawer === 'agent' && hasManagedRequestScope(managedScope),
  })

  const envId = session?.environment_id
  const { data: envDetail } = useQuery({
    queryKey: ['environment', sessionScope, envId],
    queryFn: () =>
      managedGet<Environment>(
        apiResourcePath('environments', envId!),
        managedRequestOptions(managedScope),
      ),
    enabled: !!envId && hasManagedRequestScope(managedScope),
  })

  const vaultId = session?.vault_ids?.[0]
  const { data: vaultDetail } = useQuery({
    queryKey: ['vault', sessionScope, vaultId],
    queryFn: () =>
      managedGet<Vault>(apiResourcePath('vaults', vaultId!), managedRequestOptions(managedScope)),
    enabled: !!vaultId && hasManagedRequestScope(managedScope),
  })

  const { data: vaultCredentials } = useQuery({
    queryKey: ['vault-credentials', sessionScope, vaultId],
    queryFn: () =>
      managedGet<{ data: VaultCredential[] }>(
        apiResourceSubpath('vaults', vaultId!, ['credentials'], { limit: 100 }),
        managedRequestOptions(managedScope),
      ),
    enabled: !!vaultId && activeDrawer === 'vault' && hasManagedRequestScope(managedScope),
  })

  const { data: sessionResources } = useQuery({
    queryKey: ['session-resources', sessionScope],
    queryFn: () =>
      managedGet<{ data: SessionResource[] }>(
        apiResourcePath('sessions', id, 'resources'),
        managedRequestOptions(managedScope),
      ),
    enabled: !!id && hasManagedRequestScope(managedScope),
  })
  const { data: sessionSkillUsage } = useQuery({
    queryKey: ['session-skill-usage', sessionScope],
    queryFn: () =>
      managedGet<{ data: SessionSkillUsage[] }>(
        apiResourcePath('sessions', id, 'skill-usage'),
        managedRequestOptions(managedScope),
      ),
    enabled: !!id && hasManagedRequestScope(managedScope),
  })

  const { data: networkPolicyStatus } = useQuery({
    queryKey: ['session-network-policy', sessionScope],
    queryFn: () =>
      managedGet<NetworkPolicyStatus | null>(
        apiResourceSubpath('network-policies', 'sessions', [apiResourceId(id)]),
        managedRequestOptions(managedScope),
      ),
    enabled: !!id && hasManagedRequestScope(managedScope),
  })
  const mountedFiles = useMemo(
    () => (sessionResources?.data || []).filter((r): r is SessionFileResource => r.type === 'file'),
    [sessionResources],
  )
  const mountedRepos = useMemo(
    () =>
      (sessionResources?.data || []).filter(
        (r): r is SessionRepoResource => r.type === 'github_repository',
      ),
    [sessionResources],
  )

  const initialCachedEvents = getCachedSessionEventState(sessionScope)
  const [loadedEvents, setLoadedEvents] = useState<SessionEvent[]>(
    () => initialCachedEvents?.events ?? [],
  )
  const [hasMoreEvents, setHasMoreEvents] = useState(initialCachedEvents?.hasMoreOlder ?? true)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [eventsInitialized, setEventsInitialized] = useState(!!initialCachedEvents)
  const [streamAfterSeq, setStreamAfterSeq] = useState(() =>
    getMaxSeq(initialCachedEvents?.events ?? []),
  )
  const eventsLoadedRef = useRef(!!initialCachedEvents)
  const { events: streamEvents, connected: sseConnected } = useSessionStream(
    id || '',
    !!id && eventsInitialized,
    { initialAfterSeq: streamAfterSeq },
  )

  useEffect(() => {
    if (sessionScopeRef.current === sessionScope) return
    sessionScopeRef.current = sessionScope
    managedRequestScopeRef.current = managedScope
    actionRunRef.current += 1
    const cached = getCachedSessionEventState(sessionScope)
    const cachedEvents = cached?.events ?? []
    eventsLoadedRef.current = !!cached
    setLoadedEvents(cachedEvents)
    setHasMoreEvents(cached?.hasMoreOlder ?? true)
    setEventsInitialized(!!cached)
    setStreamAfterSeq(getMaxSeq(cachedEvents))
    setIsLoadingMore(false)
    pendingPrependScrollHeightRef.current = null
    setSelectedEvent(null)
    setActiveDrawer(null)
    setMsgInput('')
    setIsSending(false)
    setStreamForced(false)
  }, [sessionScope])

  const currentSessionScopeIsActive = useCallback(
    (scope = sessionScopeRef.current) => {
      const state = useProjectStore.getState()
      const currentScope = `${id ?? ''}:${managedScopeKey(state.currentOrgId, state.currentProjectId)}`
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

  const loadEvents = useCallback(
    async (
      cursor?: number,
      mode: 'latest' | 'older' | 'newer' = cursor == null ? 'latest' : 'newer',
    ) => {
      if (!id) return
      const actionScope = sessionScopeRef.current
      const requestScope = managedRequestScopeRef.current
      if (!currentSessionScopeIsActive(actionScope)) return
      setIsLoadingMore(true)
      try {
        const query: Record<string, string | number> = {
          limit: 100,
          order: mode === 'latest' || mode === 'older' ? 'desc' : 'asc',
        }
        if (mode === 'older' && cursor != null) query.before_seq = cursor
        if (mode === 'newer' && cursor != null) query.after_seq = cursor

        const res = await managedGet<{ data: SessionEvent[]; has_more: boolean }>(
          apiResourceSubpath('sessions', id, ['events'], query),
          managedRequestOptions(requestScope),
        )
        if (!currentSessionScopeIsActive(actionScope)) return
        const newEvents = sortSessionEvents(Array.isArray(res) ? res : res.data)
        const hasMore = Array.isArray(res) ? newEvents.length >= 100 : res.has_more

        setLoadedEvents((prev) =>
          mode === 'latest' ? newEvents : mergeSessionEvents(prev, newEvents),
        )
        if (mode === 'latest') {
          setHasMoreEvents(hasMore)
          setStreamAfterSeq(getMaxSeq(newEvents))
          setEventsInitialized(true)
        } else if (mode === 'older') {
          setHasMoreEvents(hasMore)
        }
      } catch {
        if (mode === 'latest' && currentSessionScopeIsActive(actionScope)) {
          setStreamAfterSeq(0)
          setEventsInitialized(true)
        }
      } finally {
        if (currentSessionScopeIsActive(actionScope)) {
          setIsLoadingMore(false)
        }
      }
    },
    [currentSessionScopeIsActive, id],
  )

  useEffect(() => {
    if (id && !eventsLoadedRef.current) {
      eventsLoadedRef.current = true
      loadEvents(undefined, 'latest')
    }
  }, [id, loadEvents])

  const loadMoreEvents = useCallback(() => {
    if (!hasMoreEvents || isLoadingMore || loadedEvents.length === 0) return
    const firstSeq = getMinSeq(loadedEvents)
    if (!firstSeq) return
    pendingPrependScrollHeightRef.current = scrollContainerRef.current?.scrollHeight ?? null
    loadEvents(firstSeq, 'older')
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
    const requestScope = managedRequestScopeRef.current
    if (!currentSessionScopeIsActive(actionScope)) return
    const sessionId = id
    setIsSending(true)
    setMsgInput('')
    setStreamForced(true)
    try {
      await managedPost(
        apiResourcePath('sessions', sessionId, 'events'),
        {
          events: [{ type: 'user.message', content: [{ type: 'text', text }] }],
        },
        {
          ...managedRequestOptions(requestScope),
          headers: {
            ...managedRequestOptions(requestScope).headers,
            'Idempotency-Key': `session-message:${generateUUID()}`,
          },
        },
      )
      if (!isCurrentAction(runId, actionScope)) return
      queryClient.invalidateQueries({ queryKey: ['session', actionScope] })
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
      const requestScope = managedRequestScopeRef.current
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
        await managedPost(
          apiResourcePath('sessions', sessionId, 'events'),
          {
            events: [payload],
          },
          managedRequestOptions(requestScope),
        )
        if (!isCurrentAction(runId, actionScope)) return
        queryClient.invalidateQueries({ queryKey: ['session', actionScope] })
      } catch (e) {
        if (!isCurrentAction(runId, actionScope)) return
        toastOperationError(t, e, 'common.operationFailed')
      } finally {
        if (isCurrentAction(runId, actionScope)) {
          setApprovingCallId(null)
        }
      }
    },
    [id, queryClient, t, isCurrentAction, currentSessionDetail],
  )

  const handleArchiveSession = async () => {
    if (!id) return
    if (!currentProjectAllowsWrite()) return
    const current = currentSessionDetail()
    if (!current || current.archived_at) return
    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    const actionScope = sessionScopeRef.current
    const requestScope = managedRequestScopeRef.current
    if (!currentSessionScopeIsActive(actionScope)) return
    const sessionId = id
    try {
      await managedPost(
        apiResourcePath('sessions', sessionId, 'archive'),
        {},
        managedRequestOptions(requestScope),
      )
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
    const requestScope = managedRequestScopeRef.current
    if (!currentSessionScopeIsActive(actionScope)) return
    const sessionId = id
    try {
      await managedPost(
        apiResourcePath('sessions', sessionId, 'stop'),
        {},
        managedRequestOptions(requestScope),
      )
      if (!isCurrentAction(runId, actionScope)) return
      queryClient.invalidateQueries({ queryKey: ['session', actionScope] })
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

  useEffect(() => {
    if (!id || !eventsInitialized) return
    setCachedSessionEventState(sessionScope, allEvents, hasMoreEvents)
  }, [allEvents, eventsInitialized, hasMoreEvents, id, sessionScope])

  useEffect(() => {
    const previousHeight = pendingPrependScrollHeightRef.current
    if (previousHeight == null) return
    const el = scrollContainerRef.current
    pendingPrependScrollHeightRef.current = null
    if (!el) return
    const delta = el.scrollHeight - previousHeight
    if (delta > 0) el.scrollTop += delta
  }, [loadedEvents.length])

  // Pending tool-confirmation approvals (always_ask): control_request events
  // that have no matching user.tool_confirmation reply yet.
  const pendingApprovals = useMemo(() => {
    const confirmed = new Set<string>()
    for (const evt of allEvents) {
      const t = evt.type || evt.event_type || ''
      if (t === 'user.tool_confirmation') {
        const cid =
          (evt as { call_id?: string; tool_use_id?: string }).call_id ||
          (evt as { tool_use_id?: string }).tool_use_id
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
        const prevType = prev ? prev.type || prev.event_type || '' : ''
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
        if (
          (t === 'agent.tool_result' || t === 'agent.mcp_tool_result') &&
          callId &&
          !seenResultCallIds.has(callId)
        ) {
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
    const TOOL_USE_TYPES_SET = new Set([
      'agent.tool_use',
      'agent.mcp_tool_use',
      'agent.custom_tool_use',
    ])
    const TOOL_RESULT_TYPES_SET = new Set([
      'agent.tool_result',
      'agent.mcp_tool_result',
      'user.tool_result',
      'user.custom_tool_result',
    ])
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
      const prevType = prev ? prev.type || prev.event_type || '' : ''

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
              merged[j] = {
                ...candidate,
                is_error: candidate.is_error || evt.is_error || false,
                duration_ms: durationMs,
              }
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
    if (
      tab !== 'transcript' ||
      searchText ||
      !hasMoreEvents ||
      isLoadingMore ||
      loadedEvents.length === 0
    )
      return

    if (filteredEvents.length < MIN_TRANSCRIPT_EVENTS) {
      loadMoreEvents()
    }
  }, [
    tab,
    searchText,
    hasMoreEvents,
    isLoadingMore,
    loadedEvents.length,
    filteredEvents.length,
    loadMoreEvents,
  ])

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
        const endMs = session?.status === 'running' ? Date.now() : Math.max(lastEventMs, runningAt)
        total += (endMs - runningAt) / 1000
      }
      if (total > 0) return Math.round(total)
    }
    const statsDur =
      session?.stats?.duration_seconds ??
      (session?.stats?.duration_ms ? session.stats.duration_ms / 1000 : 0)
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
    return <div className="p-8 text-muted-foreground">{t('common.loading')}</div>
  }

  const sessionStart = session.created_at

  // Build metadata items
  const metaItems: { icon: ReactNode; label: ReactNode; tooltip?: string; onClick?: () => void }[] =
    []
  if (session.agent) {
    metaItems.push({
      icon: <Package className="h-3.5 w-3.5" />,
      label: session.agent.name,
      tooltip: session.agent.name,
      onClick: () => setActiveDrawer('agent'),
    })
  }
  if (session.environment_id) {
    metaItems.push({
      icon: <Globe className="h-3.5 w-3.5" />,
      label: envDetail?.name || stripIdPrefix(session.environment_id).slice(0, 12),
      tooltip: envDetail?.name || session.environment_id,
      onClick: () => setActiveDrawer('env'),
    })
  }
  if (session.vault_ids && session.vault_ids.length > 0) {
    metaItems.push({
      icon: <KeyRound className="h-3.5 w-3.5" />,
      label:
        vaultDetail?.name ||
        (session.vault_ids.length > 1
          ? `${session.vault_ids.length} vaults`
          : stripIdPrefix(session.vault_ids[0]).slice(0, 12)),
      tooltip: vaultDetail?.name || session.vault_ids[0],
      onClick: () => setActiveDrawer('vault'),
    })
  }
  // Duration
  const durationSec =
    session.stats?.duration_seconds ??
    (session.stats?.duration_ms ? session.stats.duration_ms / 1000 : 0)
  if (durationSec > 0) {
    const m = Math.floor(durationSec / 60)
    const s = Math.round(durationSec % 60)
    metaItems.push({
      icon: <Timer className="h-3.5 w-3.5" />,
      label: m > 0 ? `${m}m ${s}s` : `${s}s`,
    })
  }
  // Token usage
  if (session.usage && (session.usage.input_tokens > 0 || session.usage.output_tokens > 0)) {
    const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n))
    metaItems.push({
      icon: <MessageSquare className="h-3.5 w-3.5" />,
      label: `${fmt(session.usage.input_tokens)}/${fmt(session.usage.output_tokens)}`,
    })
  }
  // Mounted files
  if (mountedFiles.length > 0) {
    metaItems.push({
      icon: <FileIcon className="h-3.5 w-3.5" />,
      label: `${mountedFiles.length} ${t('managed.sessions.create.resources').toLowerCase()}`,
      onClick: () => setActiveDrawer('files'),
    })
  }
  // Mounted repos
  if (mountedRepos.length > 0) {
    metaItems.push({
      icon: <GitBranch className="h-3.5 w-3.5" />,
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
      icon: <Timer className="h-3.5 w-3.5" />,
      label: runtimeLabel,
      tooltip: t('managed.sessions.runtimeDuration'),
    })
  }
  // Created time
  metaItems.push({
    icon: <Clock className="h-3.5 w-3.5" />,
    label: formatRelativeTime(session.created_at),
  })

  const sessionDisplayName = formatSessionId(session.id)

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      {/* Header */}
      <div className="shrink-0">
        <PageHeader
          title={sessionDisplayName}
          titleExtra={<StatusBadge status={displayStatus} />}
          breadcrumb={[
            { label: t('managed.sessions.title'), to: '/managed/sessions' },
            { label: sessionDisplayName },
          ]}
          action={
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={openSessionFiles}>
                <Folder className="mr-1.5 h-3.5 w-3.5" />
                {t('managed.sessions.filesAndOutputs')}
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm">
                    {t('managed.sessions.actions')}
                    <ChevronDown className="ml-1 h-3.5 w-3.5" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onSelect={handleStopSession}
                    disabled={projectReadOnly || !isRunning || isArchived}
                  >
                    <StopCircle className="mr-2 h-3.5 w-3.5" />
                    {t('managed.sessions.stopSession')}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onSelect={handleArchiveSession}
                    disabled={projectReadOnly || isArchived}
                  >
                    <Archive className="mr-2 h-3.5 w-3.5" />
                    {t('managed.sessions.archive')}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          }
        />

        {/* Metadata bar - own line */}
        <div className="-mt-3 mb-4 flex items-center gap-1 text-sm text-muted-foreground">
          {metaItems.map((item, i) => (
            <span key={i} className="contents">
              {i > 0 && <span className="mx-1.5">&middot;</span>}
              <button
                type="button"
                title={item.tooltip}
                className={`inline-flex items-center gap-1.5 ${item.onClick ? 'cursor-pointer hover:text-foreground' : 'cursor-default'} transition-colors`}
                onClick={item.onClick}
                disabled={!item.onClick}
              >
                {item.icon}
                <span>{item.label}</span>
              </button>
            </span>
          ))}
        </div>
        <div className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border bg-muted/30 px-3 py-2 text-xs">
          <div className="flex items-center gap-1.5 font-medium text-foreground">
            {networkPolicyStatus?.networking_last_error ? (
              <AlertTriangle className="h-3.5 w-3.5 text-destructive" />
            ) : (
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
            )}
            {t('managed.sessions.networkPolicy.title')}
          </div>
          {networkPolicyStatus ? (
            <>
              <Badge variant="outline">{networkPolicyStatus.networking_status}</Badge>
              <span className="text-muted-foreground">
                {t('managed.sessions.networkPolicy.version', {
                  version: networkPolicyStatus.networking_policy_version || 0,
                })}
              </span>
              {networkPolicyStatus.networking_policy_hash ? (
                <code className="rounded bg-background px-1.5 py-0.5 text-[11px]">
                  {networkPolicyStatus.networking_policy_hash.slice(0, 12)}
                </code>
              ) : null}
              {networkPolicyStatus.networking_ready_at ? (
                <span className="text-muted-foreground">
                  {t('managed.sessions.networkPolicy.readyAt')}{' '}
                  <RelativeTime date={networkPolicyStatus.networking_ready_at} />
                </span>
              ) : null}
              {networkPolicyStatus.networking_last_error ? (
                <span
                  className="min-w-0 flex-1 truncate text-destructive"
                  title={networkPolicyStatus.networking_last_error}
                >
                  {networkPolicyStatus.networking_last_error}
                </span>
              ) : null}
            </>
          ) : (
            <span className="text-muted-foreground">
              {t('managed.sessions.networkPolicy.empty')}
            </span>
          )}
        </div>
      </div>

      {/* Tab bar + toolbar */}
      <div className="mb-0 flex shrink-0 items-center justify-between border-b border-border pb-0">
        <div className="flex items-center gap-4">
          <Tabs value={tab} onValueChange={(v) => setTab(v as 'transcript' | 'debug')}>
            <TabsList>
              <TabsTrigger value="transcript">{t('managed.sessions.tab.transcript')}</TabsTrigger>
              <TabsTrigger value="debug">{t('managed.sessions.tab.debug')}</TabsTrigger>
            </TabsList>
          </Tabs>

          <EventFilter
            selected={debugFilter}
            onChange={setDebugFilter}
            availableTypes={availableTypes}
          />

          <button
            type="button"
            className="text-muted-foreground transition-colors hover:text-foreground"
            onClick={() => setShowSearch(!showSearch)}
          >
            <Search className="h-4 w-4" />
          </button>
        </div>

        <div className="flex items-center gap-2 pb-1">
          {isRunning && <Circle className="h-3 w-3 fill-red-500 text-red-500" />}
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => navigator.clipboard.writeText(JSON.stringify(allEvents, null, 2))}
          >
            <Copy className="mr-1 h-3 w-3" />
            {t('managed.sessions.copyAll')}
          </Button>
        </div>
      </div>

      {/* Search bar */}
      {showSearch && (
        <div className="shrink-0 pt-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="session-search"
              autoFocus
              placeholder={t('managed.sessions.searchEvents')}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              className="h-7 w-[240px] pl-7 text-xs"
            />
          </div>
        </div>
      )}

      {/* Timeline */}
      <div className="mt-3 shrink-0">
        <EventTimeline
          events={filteredEvents}
          sessionStart={sessionStart}
          selectedId={selectedEvent?.id || null}
          onSelect={setSelectedEvent}
        />
      </div>

      {/* Content: event list + detail panel */}
      <div className="flex flex-1 overflow-hidden rounded-lg border border-border">
        <div
          ref={scrollContainerRef}
          className="flex-1 overflow-y-auto"
          onScroll={(e) => {
            const el = e.currentTarget
            const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
            // Pin to bottom only when the user is within 80px of it, so live events
            // keep following; scrolling up to read history releases the pin.
            stickToBottomRef.current = distanceFromBottom < 80
            if (el.scrollTop < 100 && hasMoreEvents && !isLoadingMore) {
              loadMoreEvents()
            }
          }}
        >
          {isLoadingMore && (
            <div className="flex justify-center py-3">
              <span className="text-xs text-muted-foreground">{t('common.loading')}</span>
            </div>
          )}
          <EventList
            events={filteredEvents}
            sessionStart={sessionStart}
            selectedId={selectedEvent?.id || null}
            onSelect={setSelectedEvent}
            mode={tab}
          />
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
        <div className="shrink-0 space-y-2 border-t border-amber-300 bg-amber-50 px-3 py-2 dark:bg-amber-950/30">
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
                className="flex items-start gap-3 rounded-md border border-amber-300 bg-white p-2 dark:bg-background"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-medium text-amber-800 dark:text-amber-300">
                    {t('managed.sessions.events.approvalBannerTitle', { tool: p.tool })}
                  </div>
                  {previewText && (
                    <div className="mt-1 truncate font-mono text-xs text-muted-foreground">
                      {previewText}
                    </div>
                  )}
                  <Input
                    className="mt-2 h-7 text-xs"
                    placeholder={t('managed.sessions.events.approvalDenyPlaceholder')}
                    value={denyDraft[p.callId] || ''}
                    onChange={(e) =>
                      setDenyDraft((prev) => ({ ...prev, [p.callId]: e.target.value }))
                    }
                    disabled={projectReadOnly || sending}
                  />
                </div>
                <div className="flex shrink-0 flex-col gap-1">
                  <Button
                    size="sm"
                    className="h-7 bg-emerald-500 px-3 text-white hover:bg-emerald-600"
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
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            value={msgInput}
            onChange={(e) => setMsgInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSendMessage()
              }
            }}
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
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Drawers */}
      {activeDrawer === 'agent' && (
        <AgentDrawer
          session={session}
          agent={agentDetail || null}
          skillUsage={sessionSkillUsage?.data || []}
          queryScope={sessionScope}
          requestScope={managedScope}
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
          sessionId={id}
          operationScope={sessionScope}
          requestScope={managedScope}
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
          sessionId={id}
          operationScope={sessionScope}
          requestScope={managedScope}
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
  skillUsage,
  queryScope,
  requestScope,
  onClose,
  onGoToAgent,
}: {
  session: Session
  agent: Agent | null
  skillUsage: SessionSkillUsage[]
  queryScope: string
  requestScope: ManagedRequestScope
  onClose: () => void
  onGoToAgent: () => void
}) {
  const { t } = useTranslation()
  const [promptExpanded, setPromptExpanded] = useState(true)
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)
  const [versionDropdownOpen, setVersionDropdownOpen] = useState(false)

  const agentId = agent?.id || session.agent?.id
  const rawAgentId = agentId ? apiResourceId(agentId) : null

  const { data: versionsData } = useQuery({
    queryKey: ['agent-versions', queryScope, rawAgentId],
    queryFn: () =>
      managedGet<{ data: AgentVersionEntry[] }>(
        apiResourcePath('agents', rawAgentId, 'versions'),
        managedRequestOptions(requestScope),
      ),
    enabled: !!rawAgentId && hasManagedRequestScope(requestScope),
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
  const configuredSkills = displayAgent?.skills || []

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      <div className="relative h-full w-[480px] max-w-full overflow-y-auto border-l border-border bg-background shadow-xl">
        <Button
          variant="ghost"
          size="icon"
          className="absolute right-4 top-4 z-10 h-8 w-8"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </Button>

        <div className="space-y-6 px-6 py-5">
          {/* Header */}
          <section>
            <h2 className="text-base font-semibold text-foreground">{agentName}</h2>
            <div className="mt-1 space-y-0.5 text-xs text-muted-foreground">
              {displayAgent && (
                <div className="font-mono">
                  <MonoId id={displayAgent.id} truncate={false} />
                </div>
              )}
              <button
                className="inline-flex items-center gap-1 text-primary hover:underline"
                onClick={onGoToAgent}
              >
                {t('managed.sessions.goToAgent')} <ArrowRight className="h-3 w-3" />
              </button>
            </div>
          </section>

          {/* Version selector */}
          <section>
            <div className="relative">
              <button
                type="button"
                className="flex w-full items-center justify-between rounded-lg border border-border px-3 py-2 text-sm text-foreground transition-colors hover:bg-muted/50"
                onClick={() => setVersionDropdownOpen(!versionDropdownOpen)}
              >
                <span>
                  {t('managed.sessions.version')}: v{activeVersion}
                </span>
                <ChevronDown
                  className={`h-4 w-4 text-muted-foreground transition-transform ${versionDropdownOpen ? 'rotate-180' : ''}`}
                />
              </button>
              {versionDropdownOpen && versions.length > 0 && (
                <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-border bg-background shadow-lg">
                  {versions.map((v) => (
                    <button
                      key={v.version}
                      type="button"
                      className={`w-full px-3 py-2 text-left text-sm transition-colors hover:bg-muted ${v.version === activeVersion ? 'bg-muted font-medium' : ''}`}
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
            <div className="text-sm text-muted-foreground">
              {t('managed.sessions.loadingAgent')}
            </div>
          ) : (
            <>
              {/* Engine */}
              <section>
                <h3 className="mb-1 text-sm font-semibold text-foreground">
                  {t('managed.sessions.engineKind')}
                </h3>
                <p className="font-mono text-sm text-muted-foreground">
                  {displayAgent.engine_kind
                    ? ENGINE_KIND_LABELS[displayAgent.engine_kind] || displayAgent.engine_kind
                    : '-'}
                </p>
              </section>

              {/* Model */}
              <section>
                <h3 className="mb-1 text-sm font-semibold text-foreground">
                  {t('managed.sessions.model')}
                </h3>
                <p className="font-mono text-sm text-muted-foreground">
                  {displayAgent.model?.id || '-'}
                </p>
              </section>

              {/* System prompt */}
              {(displayAgent.system || displayAgent.system_prompt) && (
                <section>
                  <button
                    type="button"
                    className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-foreground"
                    onClick={() => setPromptExpanded(!promptExpanded)}
                  >
                    <ChevronRight
                      className={`h-3.5 w-3.5 transition-transform ${promptExpanded ? 'rotate-90' : ''}`}
                    />
                    {t('managed.sessions.systemPrompt')}
                  </button>
                  {promptExpanded && (
                    <pre className="max-h-[300px] overflow-x-auto overflow-y-auto whitespace-pre-wrap rounded-lg bg-muted p-4 font-mono text-xs leading-relaxed">
                      {displayAgent.system || displayAgent.system_prompt}
                    </pre>
                  )}
                </section>
              )}

              {/* MCPs and tools */}
              <section>
                <h3 className="mb-3 text-sm font-semibold text-foreground">
                  {t('managed.sessions.mcpsAndTools')}
                </h3>
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
                <h3 className="mb-2 text-sm font-semibold text-foreground">
                  {t('managed.sessions.skillsLabel')}
                </h3>
                <div className="space-y-3">
                  <div className="rounded-lg border border-border p-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-sm text-foreground">
                        {t('managed.sessions.skillsConfiguredLabel')}
                      </span>
                      <Badge variant="outline">{configuredSkills.length}</Badge>
                    </div>
                    {configuredSkills.length > 0 ? (
                      <div className="mt-2 space-y-1">
                        {configuredSkills.map((skill, i) => (
                          <div key={i} className="flex items-center justify-between gap-2 text-xs">
                            <span className="font-mono text-muted-foreground">
                              {skill.skill_id || skill.type || 'skill'}
                            </span>
                            {skill.version && <Badge variant="secondary">{skill.version}</Badge>}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="mt-2 text-sm text-muted-foreground">
                        {t('managed.sessions.noSkills')}
                      </p>
                    )}
                  </div>

                  <div className="rounded-lg border border-border p-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-sm text-foreground">
                        {t('managed.sessions.skillsActuallyLoadedLabel')}
                      </span>
                      <Badge variant={skillUsage.length > 0 ? 'default' : 'outline'}>
                        {skillUsage.length}
                      </Badge>
                    </div>
                    {skillUsage.length > 0 ? (
                      <div className="mt-3 space-y-2">
                        {skillUsage.map((usage) => (
                          <div key={usage.id} className="rounded-md bg-muted/50 p-2 text-xs">
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-mono text-foreground">
                                {usage.skill_name || usage.skill_id || 'deleted skill'}
                              </span>
                              {usage.skill_version && (
                                <Badge variant="secondary">{usage.skill_version}</Badge>
                              )}
                            </div>
                            <div className="mt-1 space-y-0.5 font-mono text-[11px] text-muted-foreground">
                              {usage.skill_id && <div>id {usage.skill_id}</div>}
                              {usage.skill_source_type && (
                                <div>source {usage.skill_source_type}</div>
                              )}
                              {usage.target && <div>target {usage.target}</div>}
                              {usage.artifact_hash && (
                                <div>artifact {usage.artifact_hash.slice(0, 12)}</div>
                              )}
                              {usage.target_hash && (
                                <div>target {usage.target_hash.slice(0, 12)}</div>
                              )}
                              {usage.security_scan_id && <div>scan {usage.security_scan_id}</div>}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="mt-2 text-sm text-muted-foreground">
                        {t('managed.sessions.noSkillUsage')}
                      </p>
                    )}
                  </div>
                </div>
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
      <div className="rounded-lg border border-border p-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted">
            <Package className="h-4 w-4 text-muted-foreground" />
          </div>
          <div>
            <div className="text-sm font-medium">{t('managed.sessions.builtInTools')}</div>
            <div className="font-mono text-xs text-muted-foreground">agent_toolset_20260401</div>
          </div>
        </div>
        <div className="mt-2 flex items-center justify-between">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            <ChevronRight
              className={`h-3.5 w-3.5 transition-transform ${expanded ? 'rotate-90' : ''}`}
            />
            {t('managed.sessions.toolPermissions')}
            {configs.length > 0 && (
              <Badge variant="outline" className="ml-1 px-1.5 py-0 text-[10px]">
                {configs.length}
              </Badge>
            )}
          </button>
          <span className="text-xs text-muted-foreground">{formatPolicy(defaultPolicy, t)}</span>
        </div>
        {expanded && configs.length > 0 && (
          <div className="ml-5 mt-2 space-y-1 border-l border-border pl-3">
            {configs.map((cfg, j) => {
              const enabled = cfg.enabled !== false
              const effectivePolicy = cfg.permission_policy?.type || defaultPolicy
              const isInherited = !cfg.permission_policy
              return (
                <div key={j} className="flex items-center justify-between py-0.5 text-xs">
                  <span className="flex items-center gap-2">
                    {enabled ? (
                      <span
                        className="inline-flex h-3.5 w-3.5 items-center justify-center rounded bg-emerald-500 text-white"
                        aria-label="enabled"
                      >
                        <svg
                          className="h-2.5 w-2.5"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth={4}
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                      </span>
                    ) : (
                      <span
                        className="inline-flex h-3.5 w-3.5 items-center justify-center rounded border border-border bg-background"
                        aria-label="disabled"
                      />
                    )}
                    <span
                      className={`font-mono ${enabled ? 'text-foreground' : 'text-muted-foreground line-through'}`}
                    >
                      {cfg.name}
                    </span>
                  </span>
                  <span className="text-muted-foreground">
                    {formatPolicy(effectivePolicy, t)}
                    {isInherited && (
                      <span className="ml-1 text-[10px] opacity-60">
                        ({t('managed.policy.inherit')})
                      </span>
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
      <div className="rounded-lg border border-border p-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted">
            <Globe className="h-4 w-4 text-muted-foreground" />
          </div>
          <div>
            <div className="text-sm font-medium">{tool.mcp_server_name}</div>
            {server && <div className="font-mono text-xs text-muted-foreground">{server.url}</div>}
          </div>
        </div>
        {(configs.length > 0 || defaultPolicy) && (
          <div className="mt-2 flex items-center justify-between">
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              <ChevronRight
                className={`h-3.5 w-3.5 transition-transform ${expanded ? 'rotate-90' : ''}`}
              />
              {t('managed.sessions.toolPermissions')}
              {configs.length > 0 && (
                <Badge variant="outline" className="ml-1 px-1.5 py-0 text-[10px]">
                  {configs.length}
                </Badge>
              )}
            </button>
            {defaultPolicy && (
              <span className="text-xs text-muted-foreground">
                {formatPolicy(defaultPolicy, t)}
              </span>
            )}
          </div>
        )}
        {expanded && configs.length > 0 && (
          <div className="ml-5 mt-2 space-y-1 border-l border-border pl-3">
            {configs.map((cfg, j) => {
              const enabled = cfg.enabled !== false
              const effectivePolicy = cfg.permission_policy?.type || defaultPolicy
              const isInherited = !cfg.permission_policy
              return (
                <div key={j} className="flex items-center justify-between py-0.5 text-xs">
                  <span className="flex items-center gap-2">
                    {enabled ? (
                      <span
                        className="inline-flex h-3.5 w-3.5 items-center justify-center rounded bg-emerald-500 text-white"
                        aria-label="enabled"
                      >
                        <svg
                          className="h-2.5 w-2.5"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth={4}
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                      </span>
                    ) : (
                      <span
                        className="inline-flex h-3.5 w-3.5 items-center justify-center rounded border border-border bg-background"
                        aria-label="disabled"
                      />
                    )}
                    <span
                      className={`font-mono ${enabled ? 'text-foreground' : 'text-muted-foreground line-through'}`}
                    >
                      {cfg.name}
                    </span>
                  </span>
                  <span className="text-muted-foreground">
                    {formatPolicy(effectivePolicy, t)}
                    {isInherited && (
                      <span className="ml-1 text-[10px] opacity-60">
                        ({t('managed.policy.inherit')})
                      </span>
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
      <div className="rounded-lg border border-border p-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted">
            <Package className="h-4 w-4 text-muted-foreground" />
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
    case 'always_allow':
      return t('managed.policy.alwaysAllow')
    case 'always_ask':
      return t('managed.policy.alwaysAsk')
    case 'always_deny':
      return t('managed.policy.alwaysDeny')
    case 'ask':
      return t('managed.policy.ask')
    case 'inherit':
      return t('managed.policy.inherit')
    default:
      return policy.replace(/_/g, ' ')
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
  const hasPackages =
    packages &&
    (packages.apt?.length ?? 0) +
      (packages.pip?.length ?? 0) +
      (packages.npm?.length ?? 0) +
      (packages.cargo?.length ?? 0) +
      (packages.gem?.length ?? 0) +
      (packages.go?.length ?? 0) >
      0

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      <div className="relative h-full w-[480px] max-w-full overflow-y-auto border-l border-border bg-background shadow-xl">
        <Button
          variant="ghost"
          size="icon"
          className="absolute right-4 top-4 z-10 h-8 w-8"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </Button>

        <div className="space-y-6 px-6 py-5">
          {/* Header */}
          <section>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold text-foreground">{env.name}</h2>
              <StatusBadge status={isArchived ? 'archived' : 'active'} />
              <Badge variant="outline" className="text-xs capitalize">
                {envType}
              </Badge>
            </div>
            {env.description && (
              <p className="mt-1 text-sm text-muted-foreground">{env.description}</p>
            )}
            <div className="mt-1.5 space-y-0.5 text-xs text-muted-foreground">
              <div className="font-mono">
                <MonoId id={env.id} truncate={false} />
              </div>
              <button
                className="inline-flex items-center gap-1 text-primary hover:underline"
                onClick={onGoToEnv}
              >
                {t('managed.sessions.goToEnv')} <ArrowRight className="h-3 w-3" />
              </button>
            </div>
          </section>

          {/* Overview */}
          <section>
            <h3 className="mb-3 text-sm font-semibold text-foreground">
              {t('managed.sessions.overview')}
            </h3>
            <div className="space-y-2">
              <div className="flex items-center text-sm">
                <span className="w-28 shrink-0 text-muted-foreground">
                  {t('managed.sessions.scope')}
                </span>
                <span className="text-foreground">{t('managed.sessions.organization')}</span>
              </div>
              <div className="flex items-center text-sm">
                <span className="w-28 shrink-0 text-muted-foreground">
                  {t('managed.sessions.created')}
                </span>
                <span className="text-foreground">{formatRelativeTime(env.created_at)}</span>
              </div>
            </div>
          </section>

          {/* Networking */}
          <section>
            <h3 className="mb-1 text-sm font-semibold text-foreground">
              {t('managed.sessions.networking')}
            </h3>
            <p className="mb-3 text-xs text-muted-foreground">
              {t('managed.sessions.networkingDesc')}
            </p>
            <div className="space-y-2">
              <div className="flex items-center text-sm">
                <span className="w-28 shrink-0 text-muted-foreground">
                  {t('managed.sessions.type')}
                </span>
                <span className="capitalize text-foreground">{networking?.type || 'limited'}</span>
              </div>
              <div className="flex items-center text-sm">
                <span className="w-28 shrink-0 text-muted-foreground">
                  {t('managed.sessions.mcpAccess')}
                </span>
                <span className="text-foreground">
                  {networking?.allow_mcp_servers
                    ? t('managed.sessions.enabled')
                    : t('managed.sessions.disabled')}
                </span>
              </div>
              {networking?.allowed_hosts && networking.allowed_hosts.length > 0 && (
                <div className="flex items-start text-sm">
                  <span className="w-28 shrink-0 pt-0.5 text-muted-foreground">
                    {t('managed.sessions.hosts')}
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {networking.allowed_hosts.map((host) => (
                      <code key={host} className="rounded bg-muted px-2 py-0.5 font-mono text-xs">
                        {host}
                      </code>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </section>

          {/* Packages — hidden for now */}

          {/* Environment Variables */}
          <section>
            <h3 className="mb-2 text-sm font-semibold text-foreground">
              {t('managed.sessions.envVars', '环境变量')}
            </h3>
            {env.config?.env_vars && Object.keys(env.config.env_vars).length > 0 ? (
              <div className="space-y-1.5">
                {Object.entries(env.config.env_vars).map(([key, value]) => (
                  <div key={key} className="flex items-start text-sm">
                    <code
                      className="w-36 shrink-0 truncate font-mono text-xs text-muted-foreground"
                      title={key}
                    >
                      {key}
                    </code>
                    <code className="min-w-0 flex-1 truncate font-mono text-xs text-foreground">
                      ••••••
                    </code>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm italic text-muted-foreground">
                {t('managed.sessions.noneConfigured')}
              </p>
            )}
          </section>

          {/* Egress Services (第三方服务) */}
          <section>
            <h3 className="mb-2 text-sm font-semibold text-foreground">
              {t('managed.sessions.egressServices', '第三方服务')}
            </h3>
            {env.config?.egress_services && env.config.egress_services.length > 0 ? (
              <div className="space-y-2">
                {env.config.egress_services.map(
                  (svc: { name?: string; base_url?: string }, i: number) => (
                    <div key={i} className="border-border/60 rounded border px-3 py-2">
                      {svc.name && (
                        <div className="text-sm font-medium text-foreground">{svc.name}</div>
                      )}
                      {svc.base_url && (
                        <code className="text-xs text-muted-foreground">{svc.base_url}</code>
                      )}
                    </div>
                  ),
                )}
              </div>
            ) : (
              <p className="text-sm italic text-muted-foreground">
                {t('managed.sessions.noneConfigured')}
              </p>
            )}
          </section>

          {/* Storage Volumes (数据卷挂载) */}
          <section>
            <h3 className="mb-2 text-sm font-semibold text-foreground">
              {t('managed.sessions.storageVolumes', '数据卷挂载')}
            </h3>
            {env.config?.storage_volumes && env.config.storage_volumes.length > 0 ? (
              <div className="space-y-2">
                {env.config.storage_volumes.map(
                  (vol: { name?: string; mount_path?: string; volume_id?: string }, i: number) => (
                    <div key={i} className="flex items-center text-sm">
                      <span className="w-28 shrink-0 text-muted-foreground">
                        {vol.name || vol.volume_id || `vol-${i}`}
                      </span>
                      <code className="font-mono text-xs text-foreground">
                        {vol.mount_path || '-'}
                      </code>
                    </div>
                  ),
                )}
              </div>
            ) : (
              <p className="text-sm italic text-muted-foreground">
                {t('managed.sessions.noneConfigured')}
              </p>
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
      <div className="relative h-full w-[480px] max-w-full overflow-y-auto border-l border-border bg-background shadow-xl">
        <div className="sticky top-0 flex items-center justify-between border-b border-border bg-background px-6 py-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold">{vault.name}</h2>
              <StatusBadge status={isArchived ? 'archived' : 'active'} />
            </div>
            <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
              <span>
                {t('managed.sessions.created')} <RelativeTime date={vault.created_at} />
              </span>
              <span>&middot;</span>
              <MonoId id={vault.id} />
              <span>&middot;</span>
              <button
                className="inline-flex items-center gap-1 text-primary hover:underline"
                onClick={onGoToVault}
              >
                {t('managed.sessions.goToVault')} <ArrowRight className="h-3 w-3" />
              </button>
            </div>
          </div>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="px-6 py-5">
          <h3 className="text-sm font-semibold text-foreground">
            {t('managed.sessions.credentials')}
          </h3>
          <p className="mb-4 text-xs text-muted-foreground">
            {t('managed.sessions.credentialsDesc')}
          </p>

          {activeCreds.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('managed.sessions.noCredentials')}</p>
          ) : (
            <div className="space-y-4">
              {activeCreds.map((cred) => (
                <div key={cred.id} className="space-y-1.5 rounded-lg border border-border p-4">
                  <div className="text-sm font-semibold text-foreground">{cred.name}</div>
                  <div className="font-mono text-xs text-muted-foreground">
                    {cred.mcp_server_url}
                  </div>
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

type SandboxFileEntry = {
  name: string
  path: string
  file_type: 'file' | 'directory' | string
  size: number
  mtime: number
}

type SandboxFileListResponse = {
  ok: boolean
  path: string
  entries: SandboxFileEntry[]
}

type SandboxFileContentResponse = {
  ok: boolean
  path: string
  encoding?: string
  content?: string
  content_base64?: string
  content_type?: string
  filename?: string
}

function SandboxFilesPanel({
  sessionId,
  requestScope,
}: {
  sessionId: string
  requestScope: ManagedRequestScope
}) {
  const { t } = useTranslation()
  const [previewPath, setPreviewPath] = useState<string | null>(null)
  const [downloadingPath, setDownloadingPath] = useState<string | null>(null)
  const [searchText, setSearchText] = useState('')

  const previewQuery = useQuery({
    queryKey: ['session-sandbox-file-content', sessionId, requestScope.key, previewPath],
    queryFn: () =>
      managedGet<SandboxFileContentResponse>(
        apiResourceSubpath('sessions', sessionId, ['sandbox', 'files', 'content'], {
          path: previewPath || '',
        }),
        {
          ...managedRequestOptions(requestScope),
          timeout: 20000,
        },
      ),
    enabled: Boolean(previewPath) && hasManagedRequestScope(requestScope),
    retry: false,
  })

  const selectedPreview = previewPath ? previewQuery.data : null

  const downloadFile = async (targetPath: string, archive = false) => {
    setDownloadingPath(targetPath)
    try {
      const endpoint = apiResourceSubpath(
        'sessions',
        sessionId,
        ['sandbox', 'files', archive ? 'archive' : 'raw'],
        { path: targetPath },
      )
      const response = await managedFetchResponse(endpoint, managedRequestOptions(requestScope))
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = getDownloadFilename(response, targetPath, archive)
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (downloadError) {
      toastOperationError(t, downloadError, 'common.operationFailed')
    } finally {
      setDownloadingPath(null)
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-border bg-background px-5 py-4">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
            placeholder={t('managed.sessions.searchFiles')}
            className="h-10 pl-9"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <SandboxDirectoryTree
          sessionId={sessionId}
          requestScope={requestScope}
          path="/workspace"
          name="workspace"
          level={0}
          defaultExpanded
          searchText={searchText}
          downloadingPath={downloadingPath}
          onPreview={setPreviewPath}
          onDownload={(filePath) => downloadFile(filePath, false)}
        />

        {previewPath && (
          <div className="mt-4 rounded-lg border border-border bg-muted/20 p-3">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold">{t('managed.sessions.filePreview')}</h3>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2"
                onClick={() => setPreviewPath(null)}
              >
                {t('common.close')}
              </Button>
            </div>
            {previewQuery.isLoading ? (
              <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
            ) : previewQuery.error ? (
              <p className="text-sm text-muted-foreground">
                {t('managed.sessions.previewUnavailable')}
              </p>
            ) : selectedPreview?.encoding === 'base64' ? (
              <div className="rounded-lg border border-dashed border-border bg-background p-3 text-sm text-muted-foreground">
                {t('managed.sessions.binaryPreviewUnavailable')}
              </div>
            ) : (
              <div className="flex max-h-64 flex-col overflow-hidden rounded-lg border border-border bg-background">
                <div className="border-b border-border px-3 py-2 font-mono text-xs text-muted-foreground">
                  {previewPath}
                </div>
                <pre className="min-h-0 flex-1 overflow-auto p-3 text-xs leading-5">
                  {selectedPreview?.content || ''}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function SandboxDirectoryTree({
  sessionId,
  requestScope,
  path,
  name,
  level,
  defaultExpanded = false,
  searchText,
  downloadingPath,
  onPreview,
  onDownload,
}: {
  sessionId: string
  requestScope: ManagedRequestScope
  path: string
  name: string
  level: number
  defaultExpanded?: boolean
  searchText: string
  downloadingPath: string | null
  onPreview: (path: string) => void
  onDownload: (path: string) => void
}) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(defaultExpanded)
  const normalizedSearch = searchText.trim().toLowerCase()
  const { data, isLoading, error } = useQuery({
    queryKey: ['session-sandbox-files', sessionId, requestScope.key, path],
    queryFn: () =>
      managedGet<SandboxFileListResponse>(
        apiResourceSubpath('sessions', sessionId, ['sandbox', 'files'], { path }),
        {
          ...managedRequestOptions(requestScope),
          timeout: 20000,
        },
      ),
    enabled: expanded && Boolean(sessionId) && hasManagedRequestScope(requestScope),
    retry: false,
  })
  const entries = (data?.entries || []).filter((entry) => {
    if (!normalizedSearch) return true
    return entry.name.toLowerCase().includes(normalizedSearch) || entry.file_type === 'directory'
  })

  return (
    <div>
      <button
        type="button"
        className="flex h-9 w-full items-center gap-2 rounded-md px-2 text-left text-sm hover:bg-muted/50"
        style={{ paddingLeft: 8 + level * 20 }}
        onClick={() => setExpanded((value) => !value)}
      >
        <ChevronDown
          className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${expanded ? '' : '-rotate-90'}`}
        />
        <Folder className="h-4 w-4 text-sky-500" />
        <span className="truncate font-medium text-foreground">{name}</span>
      </button>

      {expanded && (
        <div className="border-border/60 border-l" style={{ marginLeft: 18 + level * 20 }}>
          {isLoading ? (
            <div className="px-3 py-2 text-sm text-muted-foreground">{t('common.loading')}</div>
          ) : error ? (
            <div className="px-3 py-2 text-sm text-muted-foreground">
              {t('managed.sessions.sandboxFilesUnavailable')}
            </div>
          ) : entries.length === 0 ? (
            <div className="px-3 py-2 text-sm text-muted-foreground">
              {t('managed.sessions.emptySandboxFiles')}
            </div>
          ) : (
            entries.map((entry) =>
              entry.file_type === 'directory' ? (
                <SandboxDirectoryTree
                  key={entry.path}
                  sessionId={sessionId}
                  requestScope={requestScope}
                  path={entry.path}
                  name={entry.name}
                  level={level + 1}
                  searchText={searchText}
                  downloadingPath={downloadingPath}
                  onPreview={onPreview}
                  onDownload={onDownload}
                />
              ) : (
                <div
                  key={entry.path}
                  className="group ml-2 flex h-10 items-center gap-2 rounded-md px-2 hover:bg-muted/50"
                  style={{ paddingLeft: 8 + level * 20 }}
                >
                  <button
                    type="button"
                    className="flex min-w-0 flex-1 items-center gap-2 text-left"
                    onClick={() => onPreview(entry.path)}
                    title={t('managed.sessions.previewFile')}
                  >
                    <FileIcon className="h-4 w-4 shrink-0 text-sky-500" />
                    <span className="truncate text-sm text-foreground">{entry.name}</span>
                  </button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-muted-foreground opacity-80 hover:text-foreground group-hover:opacity-100"
                    onClick={() => onDownload(entry.path)}
                    disabled={downloadingPath === entry.path}
                    title={t('managed.sessions.downloadFile')}
                  >
                    <Download className="h-4 w-4" />
                  </Button>
                </div>
              ),
            )
          )}
        </div>
      )}
    </div>
  )
}

function FilesDrawer({
  sessionId,
  operationScope,
  requestScope,
  files,
  isIdle,
  canMutate,
  isScopeActive,
  onClose,
  onChanged,
}: {
  sessionId: string
  operationScope: string
  requestScope: ManagedRequestScope
  files: SessionFileResource[]
  isIdle: boolean
  canMutate: () => boolean
  isScopeActive: (scope: string) => boolean
  onClose: () => void
  onChanged: () => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [fileTab, setFileTab] = useState<'persistent' | 'sandbox'>('sandbox')
  const [pickerOpen, setPickerOpen] = useState(false)
  const operationScopeRef = useRef(operationScope)
  const requestScopeRef = useRef(requestScope)
  const mutationRunRef = useRef(0)
  const pickerGenerationRef = useRef(0)

  useEffect(() => {
    if (operationScopeRef.current === operationScope) {
      requestScopeRef.current = requestScope
      return
    }
    operationScopeRef.current = operationScope
    requestScopeRef.current = requestScope
    mutationRunRef.current += 1
    pickerGenerationRef.current += 1
    setPickerOpen(false)
  }, [operationScope, requestScope])

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

  const filesForAddQuery = useQuery({
    queryKey: ['files-for-add', operationScope],
    queryFn: () =>
      managedGet<{ data: FileRecord[] }>('/files?limit=100', managedRequestOptions(requestScope)),
    enabled: pickerOpen && hasManagedRequestScope(requestScope),
    retry: false,
  })

  const addFileMutation = useMutation({
    mutationFn: ({
      file,
      generation,
      runId,
      scope,
    }: {
      file: FileRecord
      generation: number
      runId: number
      scope: string
    }) => {
      if (!isCurrentMutation(runId, scope)) return Promise.resolve(undefined)
      return managedPost(
        apiResourcePath('sessions', sessionId, 'resources'),
        {
          type: 'file',
          file_id: file.id,
          mount_path: `/workspace/${file.filename}`,
        },
        managedRequestOptions(requestScopeRef.current),
      )
    },
    onSuccess: (_data, vars) => {
      if (!isCurrentMutation(vars.runId, vars.scope)) return
      onChanged()
      if (pickerGenerationRef.current === vars.generation) {
        setPickerOpen(false)
      }
    },
    onError: (error, vars) => {
      if (!isCurrentMutation(vars.runId, vars.scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const removeFileMutation = useMutation({
    mutationFn: ({
      resource,
      runId,
      scope,
    }: {
      resource: SessionFileResource
      runId: number
      scope: string
    }) => {
      if (!isCurrentMutation(runId, scope)) return Promise.resolve(undefined)
      return managedDelete(
        apiResourcePath('sessions', sessionId, 'resources', resource.id),
        managedRequestOptions(requestScopeRef.current),
      )
    },
    onSuccess: (_data, vars) => {
      if (!isCurrentMutation(vars.runId, vars.scope)) return
      onChanged()
    },
    onError: (error, vars) => {
      if (!isCurrentMutation(vars.runId, vars.scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const openFilePicker = () => {
    setFileTab('persistent')
    pickerGenerationRef.current += 1
    setPickerOpen(true)
  }

  const handleAddFile = (file: FileRecord) => {
    if (!canMutate()) return
    const currentFiles = queryClient.getQueryData<{ data?: FileRecord[] }>([
      'files-for-add',
      operationScopeRef.current,
    ])
    const currentFile = (currentFiles?.data || filesForAddQuery.data?.data || []).find(
      (candidate) => candidate.id === file.id,
    )
    if (!currentFile) return
    const action = nextMutation()
    if (!action) return
    addFileMutation.mutate({
      file: currentFile,
      generation: pickerGenerationRef.current,
      ...action,
    })
  }

  const handleRemoveFile = (resource: SessionFileResource) => {
    if (!canMutate()) return
    const currentResources = queryClient.getQueryData<{ data?: SessionResource[] }>([
      'session-resources',
      operationScopeRef.current,
    ])
    const currentFile = (currentResources?.data || files)
      .filter((candidate): candidate is SessionFileResource => candidate.type === 'file')
      .find((candidate) => candidate.id === resource.id)
    if (!currentFile) return
    const action = nextMutation()
    if (!action) return
    removeFileMutation.mutate({ resource: currentFile, ...action })
  }

  const persistentFilesContent = (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            {t('managed.sessions.persistentFiles')}
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            {t('managed.sessions.persistentFilesDesc')}
          </p>
        </div>
        <Button size="sm" disabled={!isIdle || !canMutate()} onClick={openFilePicker}>
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          {t('managed.sessions.addFile')}
        </Button>
      </div>

      {pickerOpen && (
        <div className="mb-4 rounded-lg border border-border bg-muted/20 p-3">
          {filesForAddQuery.isLoading ? (
            <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
          ) : filesForAddQuery.error ? (
            <p className="text-sm text-muted-foreground">
              {t('managed.sessions.filesUnavailable')}
            </p>
          ) : (filesForAddQuery.data?.data || []).length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t('managed.sessions.noFilesAvailable')}
            </p>
          ) : (
            <div className="space-y-1">
              {(filesForAddQuery.data?.data || []).map((file) => (
                <button
                  key={file.id}
                  type="button"
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-background"
                  onClick={() => handleAddFile(file)}
                >
                  <FileIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 truncate">{file.filename}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {files.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('managed.sessions.noOutputFiles')}</p>
      ) : (
        <div className="space-y-3">
          {files.map((f) => (
            <div key={f.id} className="space-y-1.5 rounded-lg border border-border p-3">
              <div className="flex items-center gap-2">
                <FileIcon className="h-4 w-4 text-muted-foreground" />
                <span className="min-w-0 flex-1 font-mono text-sm font-medium">{f.file_id}</span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 text-muted-foreground hover:text-destructive"
                  disabled={!isIdle || !canMutate()}
                  onClick={() => handleRemoveFile(f)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
              <div className="flex items-center text-xs text-muted-foreground">
                <span className="w-20 shrink-0">{t('managed.sessions.create.mountPath')}</span>
                <code className="rounded bg-muted px-1.5 py-0.5 font-mono">{f.mount_path}</code>
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
  )

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      <div className="relative flex h-full w-[460px] max-w-[calc(100vw-1rem)] flex-col border-l border-border bg-background shadow-xl">
        <Button
          variant="ghost"
          size="icon"
          className="absolute right-4 top-4 z-10 h-8 w-8"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </Button>

        <Tabs
          value={fileTab}
          onValueChange={(value) => setFileTab(value as 'persistent' | 'sandbox')}
          className="flex min-h-0 flex-1 flex-col"
        >
          <div className="border-b border-border px-6 pb-0 pt-5">
            <h2 className="text-xl font-semibold text-foreground">
              {t('managed.sessions.fileList')}
            </h2>
            <TabsList className="mt-5 h-auto justify-start gap-6 rounded-none bg-transparent p-0">
              <TabsTrigger
                value="persistent"
                className="relative rounded-none bg-transparent px-0 pb-3 pt-0 text-base shadow-none after:absolute after:inset-x-2 after:-bottom-px after:hidden after:h-1 after:rounded-full after:bg-foreground data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:after:block"
              >
                {t('managed.sessions.persistentFiles')}
              </TabsTrigger>
              <TabsTrigger
                value="sandbox"
                className="relative rounded-none bg-transparent px-0 pb-3 pt-0 text-base shadow-none after:absolute after:inset-x-2 after:-bottom-px after:hidden after:h-1 after:rounded-full after:bg-foreground data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:after:block"
              >
                {t('managed.sessions.runtimeSandboxFiles')}
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="sandbox" className="m-0 min-h-0 flex-1">
            <SandboxFilesPanel sessionId={sessionId} requestScope={requestScope} />
          </TabsContent>
          <TabsContent value="persistent" className="m-0 min-h-0 flex-1">
            {persistentFilesContent}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}

function ReposDrawer({
  sessionId,
  operationScope,
  requestScope,
  repos,
  isIdle,
  canMutate,
  isScopeActive,
  onClose,
  onChanged,
}: {
  sessionId: string
  operationScope: string
  requestScope: ManagedRequestScope
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
      return managedPatch(
        apiResourcePath('sessions', sessionId, 'resources', resourceId),
        {
          authorization_token: token,
        },
        managedRequestOptions(requestScope),
      )
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
      <div className="relative h-full w-[480px] max-w-full overflow-y-auto border-l border-border bg-background shadow-xl">
        <Button
          variant="ghost"
          size="icon"
          className="absolute right-4 top-4 z-10 h-8 w-8"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </Button>

        <div className="space-y-6 px-6 py-5">
          <section>
            <h2 className="text-base font-semibold text-foreground">
              {t('managed.sessions.mountedRepos')}
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              {t('managed.sessions.create.repositoriesDesc')}
            </p>
          </section>

          {repos.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('managed.sessions.noMountedRepos')}</p>
          ) : (
            <div className="space-y-3">
              {repos.map((r) => (
                <div key={r.id} className="space-y-1.5 rounded-lg border border-border p-3">
                  <div className="flex items-center gap-2">
                    <GitBranch className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="truncate font-mono text-sm font-medium">{r.url}</span>
                  </div>
                  {r.branch && (
                    <div className="flex items-center text-xs text-muted-foreground">
                      <span className="w-20 shrink-0">
                        {t('managed.sessions.create.repoBranch')}
                      </span>
                      <code className="rounded bg-muted px-1.5 py-0.5 font-mono">{r.branch}</code>
                    </div>
                  )}
                  {r.mount_path && (
                    <div className="flex items-center text-xs text-muted-foreground">
                      <span className="w-20 shrink-0">
                        {t('managed.sessions.create.mountPath')}
                      </span>
                      <code className="rounded bg-muted px-1.5 py-0.5 font-mono">
                        {r.mount_path}
                      </code>
                    </div>
                  )}
                  {isIdle && (
                    <div className="flex items-center gap-1.5 pt-1.5">
                      <Input
                        type="password"
                        autoComplete="new-password"
                        value={tokenEdits[r.id] ?? ''}
                        onChange={(e) => updateTokenDraft(r.id, e.target.value)}
                        className="h-7 font-mono text-xs"
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

function getDownloadFilename(response: Response, path: string, archive: boolean): string {
  const disposition = response.headers.get('content-disposition') || ''
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1])
    } catch {
      return utf8Match[1]
    }
  }
  const asciiMatch = disposition.match(/filename="?([^";]+)"?/i)
  if (asciiMatch?.[1]) return asciiMatch[1]
  const fallback = path.replace(/\/+$/g, '').split('/').pop() || 'workspace'
  return archive && !fallback.endsWith('.zip') ? `${fallback}.zip` : fallback
}
