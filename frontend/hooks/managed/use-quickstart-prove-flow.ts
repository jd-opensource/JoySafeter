'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  deriveQuickstartObservableChecks,
  type QuickstartObservableCheck,
} from '@/lib/managed/quickstart-acceptance-checks'
import {
  deriveQuickstartCapabilityEvidence,
  quickstartConfiguredSkillNames,
  type QuickstartAvailableSkill,
  type QuickstartCapabilityEvidence,
} from '@/lib/managed/quickstart-capabilities'
import {
  deriveQuickstartTrialStatus,
  type QuickstartTrialStatus,
} from '@/lib/managed/quickstart-trial-status'
import type { QuickstartTaskSummary, SessionEvent } from '@/types/managed'

export type QuickstartPreviewTab = 'transcript' | 'debug'

interface PreviewState {
  scopeKey: string
  tab: QuickstartPreviewTab
  filter: Set<string>
  search: string
  showSearch: boolean
  selectedEvent: SessionEvent | null
}

export interface QuickstartProveFlowController {
  preview: {
    tab: QuickstartPreviewTab
    filter: Set<string>
    search: string
    showSearch: boolean
    selectedEvent: SessionEvent | null
    availableTypes: string[]
    events: SessionEvent[]
    showTranscript: () => void
    showDebug: () => void
    setFilter: (filter: Set<string>) => void
    setSearch: (search: string) => void
    toggleSearch: () => void
    selectEvent: (event: SessionEvent) => void
    clearSelectedEvent: () => void
  }
  trial: {
    status: QuickstartTrialStatus
    capabilityEvidence: QuickstartCapabilityEvidence
    observableChecks: QuickstartObservableCheck[]
    isSessionRunning: boolean
  }
}

const TRANSCRIPT_EVENT_TYPES = new Set([
  'user.message',
  'agent.message',
  'agent.mcp_tool_use',
  'agent.mcp_tool_result',
  'agent.tool_use',
  'agent.tool_result',
  'agent.custom_tool_use',
  'user.custom_tool_result',
  'user.tool_result',
  'session.status_idle',
  'session.status_running',
  'session.status_terminated',
])

const MERGEABLE_EVENT_TYPES = new Set([
  'agent.message',
  'agent.thinking',
  'agent.tool_use',
  'agent.tool_result',
])

function createPreviewState(scopeKey: string): PreviewState {
  return {
    scopeKey,
    tab: 'debug',
    filter: new Set(),
    search: '',
    showSearch: false,
    selectedEvent: null,
  }
}

function eventText(event: SessionEvent): string {
  if (Array.isArray(event.content)) return event.content.map((block) => block.text || '').join('')
  return typeof event.content === 'string' ? event.content : ''
}

export function quickstartPreviewEventTypes(events: SessionEvent[]): string[] {
  return Array.from(
    events.reduce((types, event) => {
      if (event.type) types.add(event.type)
      return types
    }, new Set<string>()),
  ).sort()
}

export function filterAndMergeQuickstartPreviewEvents({
  events,
  tab,
  filter,
  search,
}: {
  events: SessionEvent[]
  tab: QuickstartPreviewTab
  filter: ReadonlySet<string>
  search: string
}): SessionEvent[] {
  let filtered = events
  if (tab === 'transcript') {
    filtered = events.filter((event) => TRANSCRIPT_EVENT_TYPES.has(event.type || ''))
  } else if (filter.size > 0) {
    filtered = events.filter((event) => filter.has(event.type || ''))
  }

  if (search) {
    const normalizedSearch = search.toLowerCase()
    filtered = filtered.filter((event) =>
      JSON.stringify(event).toLowerCase().includes(normalizedSearch),
    )
  }

  const merged: SessionEvent[] = []
  for (const event of filtered) {
    const eventType = event.type || ''
    if (MERGEABLE_EVENT_TYPES.has(eventType)) {
      const previous = merged[merged.length - 1]
      if (previous && (previous.type || '') === eventType) {
        if (eventType === 'agent.message' || eventType === 'agent.thinking') {
          merged[merged.length - 1] = {
            ...previous,
            content: [{ type: 'text', text: eventText(previous) + eventText(event) }],
          }
        } else {
          merged[merged.length - 1] = {
            ...previous,
            ...(event.name ? { name: event.name } : {}),
            ...(event.input !== undefined ? { input: event.input } : {}),
            ...(event.output !== undefined ? { output: event.output } : {}),
            ...(event.tool_name ? { tool_name: event.tool_name } : {}),
          }
        }
        continue
      }
    }
    merged.push(event)
  }
  return merged
}

function deriveSessionRunning(status: string | undefined, events: SessionEvent[]): boolean {
  if (status) return status === 'running'
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const eventType = events[index].type
    if (
      eventType === 'session.status_idle' ||
      eventType === 'session.status_terminated' ||
      eventType === 'task.complete'
    ) {
      return false
    }
    if (eventType === 'session.status_running' || eventType === 'user.message') return true
  }
  return false
}

export function useQuickstartProveFlow({
  scopeKey,
  isSessionActive,
  sessionStatus,
  events,
  task,
  environmentId,
  externalToolsAuthorized,
  agentConfig,
  agentMcpServerUrls,
  availableSkills,
}: {
  scopeKey: string
  isSessionActive: boolean
  sessionStatus?: string
  events: SessionEvent[]
  task: QuickstartTaskSummary | null
  environmentId?: string | null
  externalToolsAuthorized: boolean
  agentConfig?: Record<string, unknown>
  agentMcpServerUrls: string[]
  availableSkills: QuickstartAvailableSkill[]
}): QuickstartProveFlowController {
  const [storedPreview, setStoredPreview] = useState(() => createPreviewState(scopeKey))
  const [trialStatusNowMs, setTrialStatusNowMs] = useState(() => Date.now())
  const preview = storedPreview.scopeKey === scopeKey ? storedPreview : createPreviewState(scopeKey)

  const updatePreview = useCallback(
    (update: (current: PreviewState) => PreviewState) => {
      setStoredPreview((stored) =>
        update(stored.scopeKey === scopeKey ? stored : createPreviewState(scopeKey)),
      )
    },
    [scopeKey],
  )

  useEffect(() => {
    if (!task || (task.status !== 'pending' && task.status !== 'scheduling')) return
    const interval = window.setInterval(() => setTrialStatusNowMs(Date.now()), 1000)
    return () => window.clearInterval(interval)
  }, [task])

  const availableTypes = useMemo(() => quickstartPreviewEventTypes(events), [events])
  const previewEvents = useMemo(
    () =>
      filterAndMergeQuickstartPreviewEvents({
        events,
        tab: preview.tab,
        filter: preview.filter,
        search: preview.search,
      }),
    [events, preview.filter, preview.search, preview.tab],
  )
  const status = useMemo(
    () =>
      deriveQuickstartTrialStatus({
        isSessionActive,
        events,
        task,
        nowMs: trialStatusNowMs,
      }),
    [events, isSessionActive, task, trialStatusNowMs],
  )
  const capabilityEvidence = useMemo(
    () =>
      deriveQuickstartCapabilityEvidence({
        responseReceived: status === 'response_received',
        environmentId,
        externalToolsAuthorized,
        configuredSkills: quickstartConfiguredSkillNames(agentConfig, availableSkills),
        events,
      }),
    [agentConfig, availableSkills, environmentId, events, externalToolsAuthorized, status],
  )
  const observableChecks = useMemo(() => {
    const declaredArray = (key: string) =>
      Array.isArray(agentConfig?.[key]) && (agentConfig[key] as unknown[]).length > 0
    return deriveQuickstartObservableChecks({
      trialStatus: status,
      evidence: capabilityEvidence,
      hasDeclaredCapabilities:
        agentMcpServerUrls.length > 0 || declaredArray('skills') || declaredArray('tools'),
    })
  }, [agentConfig, agentMcpServerUrls.length, capabilityEvidence, status])

  return {
    preview: {
      tab: preview.tab,
      filter: preview.filter,
      search: preview.search,
      showSearch: preview.showSearch,
      selectedEvent: preview.selectedEvent,
      availableTypes,
      events: previewEvents,
      showTranscript: () =>
        updatePreview((current) => ({ ...current, tab: 'transcript', selectedEvent: null })),
      showDebug: () => updatePreview((current) => ({ ...current, tab: 'debug' })),
      setFilter: (filter) => updatePreview((current) => ({ ...current, filter })),
      setSearch: (search) => updatePreview((current) => ({ ...current, search })),
      toggleSearch: () =>
        updatePreview((current) => ({ ...current, showSearch: !current.showSearch })),
      selectEvent: (selectedEvent) =>
        updatePreview((current) => ({ ...current, tab: 'debug', selectedEvent })),
      clearSelectedEvent: () => updatePreview((current) => ({ ...current, selectedEvent: null })),
    },
    trial: {
      status,
      capabilityEvidence,
      observableChecks,
      isSessionRunning: deriveSessionRunning(sessionStatus, events),
    },
  }
}
