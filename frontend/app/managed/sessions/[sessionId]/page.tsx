'use client'

import React, { useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useMemo, useRef, useEffect, type ReactNode } from 'react'
import { i18n, useTranslation } from '@/lib/i18n'
import { Copy, Search, Package, Globe, KeyRound, Timer, MessageSquare, Clock, X, ArrowRight, Circle, Square, ChevronRight, ChevronDown, Send, Archive, StopCircle, FileIcon, Plus, Trash2 } from 'lucide-react'
import { managedGet, managedPost, managedDelete } from '@/lib/api-client'
import { shouldRetryManagedResourceError, toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
import { useSessionStream } from '@/lib/managed/sse'
import type { Agent, Environment, Vault, VaultCredential, Session, SessionEvent, AgentTool, McpServer, SessionFileResource, FileRecord } from '@/types/managed'
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
  'span.model_request_start',
  'span.model_request_end',
])

const ALL_EVENT_TYPES = new Set([
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
const STATUS_EVENT_TYPES = new Set([
  'session.status_idle',
  'session.status_rescheduled',
  'session.status_running',
  'session.status_terminated',
  'session.thread_status_idle',
  'session.thread_status_running',
  'session.thread_status_terminated',
])

function compareSessionEvents(a: SessionEvent, b: SessionEvent) {
  const seqA = a.seq ?? Number.MAX_SAFE_INTEGER
  const seqB = b.seq ?? Number.MAX_SAFE_INTEGER
  if (seqA !== seqB) return seqA - seqB

  const timeA = a.created_at ? new Date(a.created_at).getTime() : 0
  const timeB = b.created_at ? new Date(b.created_at).getTime() : 0
  if (timeA !== timeB) return timeA - timeB

  return a.id.localeCompare(b.id)
}

function sortSessionEvents(events: SessionEvent[]) {
  return [...events].sort(compareSessionEvents)
}

function getMaxSeq(events: SessionEvent[]) {
  return events.reduce((maxSeq, event) => Math.max(maxSeq, event.seq ?? 0), 0)
}

function getEventIdentity(event: SessionEvent) {
  if (event.id) return event.id
  return `${event.seq ?? 'no-seq'}:${getEventType(event)}:${JSON.stringify(event.usage ?? event.content ?? event.stop_reason ?? event.tool ?? '')}`
}

function getEventType(event: SessionEvent) {
  return event.type || event.event_type || ''
}

function getStopReasonKey(event: SessionEvent) {
  return JSON.stringify(event.stop_reason ?? '')
}

function collapseRepeatedStatusEvents(events: SessionEvent[]) {
  const collapsed: SessionEvent[] = []

  for (const event of events) {
    const eventType = getEventType(event)
    const previous = collapsed[collapsed.length - 1]
    const previousType = previous ? getEventType(previous) : ''

    if (
      previous
      && STATUS_EVENT_TYPES.has(eventType)
      && previousType === eventType
      && getStopReasonKey(previous) === getStopReasonKey(event)
    ) {
      const count = typeof previous._collapsedCount === 'number' ? previous._collapsedCount : 1
      collapsed[collapsed.length - 1] = {
        ...previous,
        id: event.id || previous.id,
        seq: event.seq ?? previous.seq,
        created_at: event.created_at || previous.created_at,
        _collapsedCount: count + 1,
      } as SessionEvent
      continue
    }

    collapsed.push(event)
  }

  return collapsed
}

function isRequiresActionIdle(event: SessionEvent) {
  return getEventType(event) === 'session.status_idle'
    && typeof event.stop_reason === 'object'
    && event.stop_reason !== null
    && (event.stop_reason as { type?: string }).type === 'requires_action'
}

function getLatestSessionStatusEvent(events: SessionEvent[]) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    const eventType = getEventType(event)
    if (eventType.startsWith('session.status_')) return event
  }

  return null
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
  const [activeDrawer, setActiveDrawer] = useState<'agent' | 'env' | 'vault' | 'files' | null>(null)
  const [msgInput, setMsgInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [streamForced, setStreamForced] = useState(false)
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)

  const { data: session, isLoading, isError, error } = useQuery({
    queryKey: ['session', id],
    queryFn: () => managedGet<Session>(`/sessions/${stripIdPrefix(id)}`),
    enabled: !!id,
    retry: shouldRetryManagedResourceError,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return (status === 'running' || streamForced) ? 2000 : false
    },
  })

  const agentId = session?.agent?.agent_id || session?.agent?.id
  const { data: agentDetail } = useQuery({
    queryKey: ['agent', agentId],
    queryFn: () => managedGet<Agent>(`/agents/${stripIdPrefix(agentId!)}`),
    enabled: !!agentId && activeDrawer === 'agent',
  })

  const envId = session?.environment_id
  const { data: envDetail } = useQuery({
    queryKey: ['environment', envId],
    queryFn: () => managedGet<Environment>(`/environments/${stripIdPrefix(envId!)}`),
    enabled: !!envId,
  })

  const vaultId = session?.vault_ids?.[0]
  const { data: vaultDetail } = useQuery({
    queryKey: ['vault', vaultId],
    queryFn: () => managedGet<Vault>(`/vaults/${stripIdPrefix(vaultId!)}`),
    enabled: !!vaultId,
  })

  const { data: vaultCredentials } = useQuery({
    queryKey: ['vault-credentials', vaultId],
    queryFn: () => managedGet<{ data: VaultCredential[] }>(`/vaults/${stripIdPrefix(vaultId!)}/credentials?limit=100`),
    enabled: !!vaultId && activeDrawer === 'vault',
  })

  const { data: sessionResources } = useQuery({
    queryKey: ['session-resources', id],
    queryFn: () => managedGet<{ data: SessionFileResource[] }>(`/sessions/${stripIdPrefix(id)}/resources`),
    enabled: !!id,
  })
  const mountedFiles = sessionResources?.data || []

  const [loadedEvents, setLoadedEvents] = useState<SessionEvent[]>([])
  const [hasMoreEvents, setHasMoreEvents] = useState(true)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const eventsLoadedRef = useRef(false)

  const loadEvents = useCallback(async (afterSeq?: number) => {
    if (!id) return
    setIsLoadingMore(true)
    try {
      const params = new URLSearchParams({ limit: '100' })
      if (afterSeq != null) params.set('after_seq', String(afterSeq))
      const res = await managedGet<{ data: SessionEvent[]; has_more: boolean }>(`/sessions/${stripIdPrefix(id)}/events?${params.toString()}`)
      const newEvents = Array.isArray(res) ? res : res.data
      const hasMore = Array.isArray(res) ? newEvents.length >= 100 : res.has_more
      setLoadedEvents((prev) => sortSessionEvents(afterSeq ? [...prev, ...newEvents] : newEvents))
      setHasMoreEvents(hasMore)
    } catch {
      // silently fail
    } finally {
      setIsLoadingMore(false)
    }
  }, [id])

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
  const canSendMessage = isIdle && !isArchived && !isSending
  const { events: streamEvents } = useSessionStream(stripIdPrefix(id || ''), !!id)
  const wasRunningRef = useRef(false)

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
    setIsSending(true)
    setMsgInput('')
    setStreamForced(true)
    try {
      await managedPost(`/sessions/${stripIdPrefix(id)}/events`, {
        events: [{ type: 'user.message', content: [{ type: 'text', text }] }],
      })
      queryClient.invalidateQueries({ queryKey: ['session', id] })
      eventsLoadedRef.current = false; setLoadedEvents([]); loadEvents()
    } catch (e) {
      toastOperationError(t, e, 'common.operationFailed')
      setStreamForced(false)
    } finally {
      setIsSending(false)
    }
  }

  const handleArchiveSession = async () => {
    if (!id) return
    try {
      await managedPost(`/sessions/${stripIdPrefix(id)}/archive`, {})
      queryClient.invalidateQueries({ queryKey: ['session', id] })
    } catch (e) {
      toastOperationError(t, e, 'common.operationFailed')
    }
  }

  const handleStopSession = async () => {
    if (!id) return
    try {
      await managedPost(`/sessions/${stripIdPrefix(id)}/stop`, {})
      queryClient.invalidateQueries({ queryKey: ['session', id] })
      eventsLoadedRef.current = false; setLoadedEvents([]); loadEvents()
    } catch (e) {
      toastOperationError(t, e, 'common.operationFailed')
    }
  }

  const allEvents = useMemo(() => {
    const base = loadedEvents
    if (streamEvents.length === 0) return base
    const lastSeq = getMaxSeq(base)
    const newOnes = streamEvents.filter((e) => (e.seq ?? 0) > lastSeq)
    const byIdentity = new Map<string, SessionEvent>()
    for (const event of [...base, ...newOnes]) byIdentity.set(getEventIdentity(event), event)
    return sortSessionEvents(Array.from(byIdentity.values()))
  }, [loadedEvents, streamEvents])

  const displayStatus = useMemo(() => {
    if (isArchived) return 'archived'
    const currentStatus = session?.status || 'idle'
    if (currentStatus !== 'idle') return currentStatus

    const latestStatusEvent = getLatestSessionStatusEvent(allEvents)
    if (latestStatusEvent && isRequiresActionIdle(latestStatusEvent)) return 'running'

    const latestStatusType = latestStatusEvent ? getEventType(latestStatusEvent) : ''
    if (latestStatusType === 'session.status_running') return 'running'
    if (latestStatusType === 'session.status_idle' || latestStatusType === 'session.status_terminated') return currentStatus

    if (streamForced) return 'running'

    return currentStatus
  }, [allEvents, isArchived, session?.status, streamForced])

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

    // Debug mode: merge text deltas, dedup tool events by call_id, pair tool_use -> tool_result
    if (tab === 'debug') {
      // Step 1: merge consecutive thinking/message text deltas
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
        if ((t === 'agent.message' || t === 'agent.thinking') && prevType === t) {
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
        if ((t === 'agent.tool_result' || t === 'agent.mcp_tool_result') && evt.call_id && !seenResultCallIds.has(evt.call_id)) {
          seenResultCallIds.add(evt.call_id)
          resultsByCallId.set(evt.call_id, evt)
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
        if ((t === 'agent.tool_use' || t === 'agent.mcp_tool_use') && evt.call_id) {
          if (seenUseCallIds.has(evt.call_id)) continue
          seenUseCallIds.add(evt.call_id)
          debugMerged.push(evt)
          const result = resultsByCallId.get(evt.call_id)
          if (result) {
            debugMerged.push(result)
            resultsByCallId.delete(evt.call_id)
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

    // Transcript mode: merge events for display matching Anthropic console:
    // 1. Consecutive agent.message / agent.thinking -> combine text
    // 2. Consecutive tool_use (parallel calls) -> deduplicate into comma-separated names
    // 3. tool_result -> fold error into preceding tool_use, compute duration from timestamps
    // 4. span.model_request_end -> attach usage (tokens) to preceding agent/tool row
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

      // Merge consecutive tool_use: deduplicate names
      if (TOOL_USE_TYPES_SET.has(t) && prev && TOOL_USE_TYPES_SET.has(prevType)) {
        const curTool = evt.tool || evt.tool_name || evt.name || ''
        const names: Set<string> = (prev as any)._toolNames || new Set((prev.tool || prev.tool_name || prev.name || '').split(', ').filter(Boolean))
        if (curTool) names.add(curTool)
        const display = Array.from(names).join(', ')
        merged[merged.length - 1] = { ...prev, tool: display, _toolNames: names } as any
        continue
      }

      // Fold tool_result into preceding tool_use -- compute duration from timestamps
      if (TOOL_RESULT_TYPES_SET.has(t) && prev && TOOL_USE_TYPES_SET.has(prevType)) {
        let durationMs = prev.duration_ms ?? 0
        if (toolUseStartTime > 0 && evt.created_at) {
          const resultTime = new Date(evt.created_at).getTime()
          if (!isNaN(resultTime)) {
            durationMs = Math.max(durationMs, resultTime - toolUseStartTime)
          }
        }
        merged[merged.length - 1] = {
          ...prev,
          is_error: (prev.is_error || evt.is_error) || false,
          duration_ms: durationMs,
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

      merged.push(evt)
    }

    return merged
  }, [allEvents, tab, debugFilter, searchText])

  useEffect(() => {
    if (tab !== 'transcript' || searchText || !hasMoreEvents || isLoadingMore || loadedEvents.length === 0) return

    if (filteredEvents.length < MIN_TRANSCRIPT_EVENTS) {
      loadMoreEvents()
    }
  }, [tab, searchText, hasMoreEvents, isLoadingMore, loadedEvents.length, filteredEvents.length, loadMoreEvents])

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
  // Created time
  metaItems.push({
    icon: <Clock className="w-3.5 h-3.5" />,
    label: formatRelativeTime(session.created_at),
  })

  const sessionDisplayName = session.title?.trim() || formatSessionId(session.id)

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
                  <DropdownMenuItem onSelect={handleStopSession} disabled={!isRunning || isArchived}>
                    <StopCircle className="w-3.5 h-3.5 mr-2" />
                    {t('managed.sessions.stopSession')}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onSelect={handleArchiveSession} disabled={isArchived}>
                    <Archive className="w-3.5 h-3.5 mr-2" />
                    {t('managed.sessions.archive')}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <Button
                size="sm"
                onClick={() => inputRef.current?.focus()}
                disabled={!canSendMessage}
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
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            title={t('managed.sessions.stopSession')}
            disabled={!isRunning}
          >
            <Square className="w-3.5 h-3.5" />
          </Button>
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
        <div className="flex-1 overflow-y-auto" onScroll={(e) => {
          const el = e.currentTarget
          if (el.scrollHeight - el.scrollTop - el.clientHeight < 100 && hasMoreEvents && !isLoadingMore) {
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

      {/* Message input */}
      <div className="shrink-0 border-t border-border px-1 py-3">
        <div className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2">
          <input
            ref={inputRef}
            className="flex-1 bg-transparent outline-none text-sm placeholder:text-muted-foreground"
            value={msgInput}
            onChange={(e) => setMsgInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage() } }}
            disabled={!canSendMessage}
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
          files={mountedFiles}
          isIdle={isIdle && !isArchived}
          onClose={() => setActiveDrawer(null)}
          onChanged={() => queryClient.invalidateQueries({ queryKey: ['session-resources', id] })}
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
  onClose,
  onGoToAgent,
}: {
  session: Session
  agent: Agent | null
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
    queryKey: ['agent-versions', rawAgentId],
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
            {configs.map((cfg, j) => (
              <div key={j} className="flex items-center justify-between text-xs py-0.5">
                <span className="font-mono text-foreground">{cfg.name}</span>
                <span className="text-muted-foreground">
                  {cfg.permission_policy ? formatPolicy(cfg.permission_policy.type, t) : '—'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  if (tool.type === 'mcp_toolset') {
    const configs = tool.configs || []
    const server = mcpServers?.find((s) => s.name === tool.mcp_server_name)
    const defaultPolicy = tool.default_config?.permission_policy?.type
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
            {configs.map((cfg, j) => (
              <div key={j} className="flex items-center justify-between text-xs py-0.5">
                <span className="font-mono text-foreground">{cfg.name}</span>
                <span className="text-muted-foreground">
                  {cfg.permission_policy ? formatPolicy(cfg.permission_policy.type, t) : '—'}
                </span>
              </div>
            ))}
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
    case 'always_allow': return t('managed.sessions.alwaysAllow')
    case 'always_deny': return t('managed.sessions.alwaysDeny')
    case 'ask': return t('managed.sessions.ask')
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
                <span className="text-foreground capitalize">{networking?.type || 'unrestricted'}</span>
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
  files,
  isIdle,
  onClose,
  onChanged,
}: {
  sessionId: string
  files: SessionFileResource[]
  isIdle: boolean
  onClose: () => void
  onChanged: () => void
}) {
  const { t } = useTranslation()
  const [showAddDropdown, setShowAddDropdown] = useState(false)
  const queryClient = useQueryClient()

  const { data: allFilesResp } = useQuery({
    queryKey: ['files-for-add'],
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
    mutationFn: (file: FileRecord) =>
      managedPost(`/sessions/${sessionId}/resources`, {
        type: 'file',
        file_id: file.id,
        mount_path: `/workspace/${file.filename}`,
      }),
    onSuccess: () => {
      onChanged()
      setShowAddDropdown(false)
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const removeFileMutation = useMutation({
    mutationFn: (resourceId: string) =>
      managedDelete(`/sessions/${sessionId}/resources/${resourceId}`),
    onSuccess: () => onChanged(),
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

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
                    onClick={() => setShowAddDropdown(!showAddDropdown)}
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
                            onClick={() => addFileMutation.mutate(f)}
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
                        onClick={() => removeFileMutation.mutate(f.id)}
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
