'use client'

import { Activity, ArrowLeft, Bot, Clock3, Loader2, Sparkles, Square } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { buildExecutionTree } from '@/components/editors/graph-builder/lib/tree-building'
import { ExecutionTree } from '@/components/execution/ExecutionTree'
import { ExecutionDetailPanel } from '@/components/execution/ExecutionDetailPanel'
import { ExecutionDataProvider } from '@/components/execution/contexts/ExecutionDataContext'
import { ExecutionSelectionProvider, useExecutionSelection } from '@/components/execution/contexts/ExecutionSelectionContext'
import { ExecutionViewPreferencesProvider } from '@/components/execution/contexts/ExecutionViewPreferencesContext'
import { useCancelRun } from '@/hooks/queries/runs'
import { useTranslation } from '@/lib/i18n'
import { ACTIVE_RUN_STATUSES, buildRunHref, formatRunStatus } from '@/lib/utils/runHelpers'
import { getRunWsClient } from '@/lib/ws/runs/runWsClient'
import type { RunEventFrame, RunSnapshotFrame, RunStatusFrame } from '@/lib/ws/runs/types'
import type { RunEvent, RunSnapshot, RunSummary } from '@/services/runService'
import { runService } from '@/services/runService'
import type { ExecutionStep } from '@/types'

function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

function buildPrimaryHref(run: RunSummary): string | null {
  const href = buildRunHref(run)
  return href === '#' ? null : href
}

function renderEventPayload(payload: Record<string, unknown>): string {
  try {
    return JSON.stringify(payload, null, 2)
  } catch {
    return String(payload)
  }
}

interface CopilotTurnProjection {
  run_type: string
  status: string
  stage?: string | null
  content?: string
  thought_steps?: Array<{ index: number; content: string }>
  tool_calls?: Array<{ tool: string; input?: Record<string, unknown> }>
  tool_results?: Array<{ type: string; payload: Record<string, unknown>; reasoning?: string }>
  result_message?: string | null
  result_actions?: Array<{ type: string; payload: Record<string, unknown>; reasoning?: string }>
  error?: string | null
  graph_id?: string | null
  mode?: string | null
}

interface ChatTurnProjection {
  run_type: 'chat_turn'
  user_message?: { content: string }
  assistant_message?: {
    content: string
    tool_calls?: Array<{
      id?: string
      name: string
      status: string
      args?: Record<string, unknown>
      result?: string
    }>
  }
  file_tree?: Record<string, { action: string; size?: number; timestamp?: number }>
  preview_data?: Record<string, unknown>
  node_execution_log?: Array<{ status: string; node_name: string }>
}

function ChatTurnOverview({
  projection: p,
  t,
}: {
  projection: Record<string, unknown>
  t: (key: string) => string
}) {
  const projection = p as unknown as ChatTurnProjection
  return (
    <div className="space-y-4">
      {projection.user_message && (
        <Card className="p-4">
          <h4 className="mb-2 text-sm font-medium text-muted-foreground">
            {t('copilot.userMessage')}
          </h4>
          <p className="whitespace-pre-wrap text-sm">{projection.user_message.content}</p>
        </Card>
      )}

      {projection.assistant_message && (
        <Card className="p-4">
          <h4 className="mb-2 text-sm font-medium text-muted-foreground">
            {t('copilot.assistantResponse')}
          </h4>
          <p className="whitespace-pre-wrap text-sm">{projection.assistant_message.content}</p>

          {projection.assistant_message.tool_calls &&
            projection.assistant_message.tool_calls.length > 0 && (
              <div className="mt-3 space-y-2">
                <h5 className="text-xs font-medium text-muted-foreground">
                  {t('copilot.toolCalls')}
                </h5>
                {projection.assistant_message.tool_calls.map((tool, i) => (
                  <details key={tool.id || i} className="rounded border p-2 text-xs">
                    <summary className="cursor-pointer font-medium">
                      {tool.name} — {tool.status}
                    </summary>
                    {tool.args && (
                      <pre className="mt-1 overflow-x-auto text-muted-foreground">
                        {JSON.stringify(tool.args, null, 2)}
                      </pre>
                    )}
                    {tool.result && (
                      <pre className="mt-1 overflow-x-auto text-muted-foreground">
                        {JSON.stringify(tool.result, null, 2)}
                      </pre>
                    )}
                  </details>
                ))}
              </div>
            )}
        </Card>
      )}

      {projection.file_tree && Object.keys(projection.file_tree).length > 0 && (
        <Card className="p-4">
          <h4 className="mb-2 text-sm font-medium text-muted-foreground">{t('copilot.files')}</h4>
          <ul className="space-y-1 text-xs">
            {Object.entries(projection.file_tree).map(([path, info]) => (
              <li key={path} className="flex items-center gap-2">
                <Badge variant="outline" className="text-xs">
                  {info.action}
                </Badge>
                <span className="truncate font-mono">{path}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {projection.preview_data && (
        <Card className="p-4">
          <h4 className="mb-2 text-sm font-medium text-muted-foreground">
            {t('copilot.preview')}
          </h4>
          <pre className="overflow-x-auto text-xs">
            {JSON.stringify(projection.preview_data, null, 2)}
          </pre>
        </Card>
      )}

      {projection.node_execution_log && projection.node_execution_log.length > 0 && (
        <Card className="p-4">
          <h4 className="mb-2 text-sm font-medium text-muted-foreground">
            {t('copilot.executionLog')}
          </h4>
          <ul className="space-y-1 text-xs">
            {projection.node_execution_log.map((entry, i) => (
              <li key={i} className="flex items-center gap-2">
                <Badge
                  variant={entry.status === 'completed' ? 'default' : 'secondary'}
                  className="text-xs"
                >
                  {entry.status}
                </Badge>
                <span className="font-mono">{entry.node_name}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}

function CopilotTurnOverview({
  projection,
  t,
}: {
  projection: CopilotTurnProjection
  t: (key: string) => string
}) {
  return (
    <div className="space-y-4">
      {/* Stage indicator */}
      {projection.stage && (
        <div className="rounded-md border p-3">
          <p className="text-sm font-medium">{t('execution.stage')}</p>
          <p className="text-sm text-muted-foreground">{projection.stage}</p>
        </div>
      )}

      {/* Mode */}
      {projection.mode && (
        <div className="rounded-md border p-3">
          <p className="text-sm font-medium">{t('execution.mode')}</p>
          <p className="text-sm text-muted-foreground">{projection.mode}</p>
        </div>
      )}

      {/* Content */}
      {projection.content && (
        <div className="rounded-md border p-3">
          <p className="text-sm font-medium">{t('execution.content')}</p>
          <p className="mt-1 whitespace-pre-wrap text-sm">{projection.content}</p>
        </div>
      )}

      {/* Thought Steps (collapsible) */}
      {projection.thought_steps && projection.thought_steps.length > 0 && (
        <details className="rounded-md border p-3">
          <summary className="cursor-pointer text-sm font-medium">
            {t('execution.thoughtSteps')} ({projection.thought_steps.length})
          </summary>
          <div className="mt-2 space-y-2">
            {projection.thought_steps.map((step, i) => (
              <div key={i} className="text-sm text-muted-foreground">
                <span className="font-mono text-xs">#{step.index}</span> {step.content}
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Tool Calls (collapsible) */}
      {projection.tool_calls && projection.tool_calls.length > 0 && (
        <details className="rounded-md border p-3">
          <summary className="cursor-pointer text-sm font-medium">
            {t('execution.toolCalls')} ({projection.tool_calls.length})
          </summary>
          <div className="mt-2 space-y-2">
            {projection.tool_calls.map((tc, i) => (
              <div key={i} className="text-sm">
                <span className="font-medium">{tc.tool}</span>
                {tc.input && (
                  <pre className="mt-1 overflow-x-auto text-xs text-muted-foreground">
                    {JSON.stringify(tc.input, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Result */}
      {projection.result_message && (
        <div className="rounded-md border border-[var(--status-success-border)] bg-[var(--status-success-bg)] p-3">
          <p className="text-sm font-medium">{t('execution.result')}</p>
          <p className="mt-1 whitespace-pre-wrap text-sm">{projection.result_message}</p>
          {projection.result_actions && projection.result_actions.length > 0 && (
            <div className="mt-2">
              <p className="text-xs font-medium text-muted-foreground">
                {projection.result_actions.length} action(s)
              </p>
              {projection.result_actions.map((action, i) => (
                <div key={i} className="mt-1 text-xs text-muted-foreground">
                  {action.type}
                  {action.reasoning ? ` — ${action.reasoning}` : ''}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {projection.error && (
        <div className="rounded-md border border-[var(--status-error-border)] bg-[var(--status-error-bg)] p-3">
          <p className="text-sm font-medium text-[var(--status-error)]">{t('execution.error')}</p>
          <p className="mt-1 text-sm text-[var(--status-error)]">{projection.error}</p>
        </div>
      )}
    </div>
  )
}

// ============ Execution Tab Helpers ============

/**
 * Converts RunEvent[] (from the run events API) to ExecutionStep[] for the
 * execution tree visualization. RunEvent.event_type + RunEvent.payload mirror
 * the ChatStreamEvent format used in the graph builder.
 */
function runEventsToExecutionSteps(events: RunEvent[]): ExecutionStep[] {
  const steps: ExecutionStep[] = []
  // Stateful maps to pair start/end events
  const toolMap = new Map<string, string>() // toolKey -> stepId
  const nodeMap = new Map<string, string>() // nodeKey -> stepId
  const modelMap = new Map<string, string>() // run_id -> stepId
  let stepCounter = 0
  const genId = (prefix: string) => `${prefix}-${++stepCounter}`

  for (const evt of events) {
    const type = evt.event_type
    const data = evt.payload as Record<string, unknown>
    const ts = evt.created_at ? new Date(evt.created_at).getTime() : Date.now()
    const traceFields: Pick<ExecutionStep, 'traceId' | 'observationId' | 'parentObservationId'> = {
      traceId: evt.trace_id ?? undefined,
      observationId: evt.observation_id ?? undefined,
      parentObservationId: evt.parent_observation_id ?? undefined,
    }
    const runId = data?.run_id as string | undefined
    const nodeName = (data?.node_name as string | undefined) ?? undefined

    if (type === 'node_start') {
      const stepId = genId('node')
      const nodeKey = runId ? `${nodeName}:${runId}` : (nodeName ?? 'unknown')
      nodeMap.set(nodeKey, stepId)
      steps.push({
        id: stepId,
        nodeId: nodeName ?? 'unknown',
        nodeLabel: (data?.node_label as string | undefined) ?? nodeName ?? 'Unknown Node',
        stepType: 'node_lifecycle',
        title: (data?.node_label as string | undefined) ?? nodeName ?? 'Node',
        status: 'running',
        startTime: ts,
        ...traceFields,
      })
    } else if (type === 'node_end') {
      const nodeKey = runId ? `${nodeName}:${runId}` : (nodeName ?? 'unknown')
      const stepId = nodeMap.get(nodeKey) ?? nodeMap.get(nodeName ?? '')
      if (stepId) {
        nodeMap.delete(nodeKey)
        const existing = steps.find((s) => s.id === stepId)
        if (existing) {
          existing.status = (data?.status === 'error' ? 'error' : 'success') as ExecutionStep['status']
          existing.endTime = ts
          if (typeof data?.duration === 'number') existing.duration = data.duration
        }
      } else {
        steps.push({
          id: genId('node'),
          nodeId: nodeName ?? 'unknown',
          nodeLabel: (data?.node_label as string | undefined) ?? nodeName ?? 'Unknown Node',
          stepType: 'node_lifecycle',
          title: (data?.node_label as string | undefined) ?? nodeName ?? 'Node',
          status: (data?.status === 'error' ? 'error' : 'success') as ExecutionStep['status'],
          startTime: ts,
          endTime: ts,
          ...traceFields,
        })
      }
    } else if (type === 'tool_start' || type === 'tool_use_start') {
      const toolName = (data?.tool_name as string | undefined) ?? 'tool'
      const toolKey = runId ? `${toolName}:${runId}` : toolName
      const stepId = genId('tool')
      toolMap.set(toolKey, stepId)
      steps.push({
        id: stepId,
        nodeId: nodeName ?? 'tool',
        nodeLabel: toolName,
        stepType: 'tool_execution',
        title: toolName,
        status: 'running',
        startTime: ts,
        data: { request: data?.tool_input ?? data?.args },
        ...traceFields,
      })
    } else if (type === 'tool_end' || type === 'tool_use_end' || type === 'tool_result') {
      const toolName = (data?.tool_name as string | undefined) ?? 'tool'
      const toolKey = runId ? `${toolName}:${runId}` : toolName
      const stepId = toolMap.get(toolKey) ?? toolMap.get(toolName)
      if (stepId) {
        toolMap.delete(toolKey)
        const existing = steps.find((s) => s.id === stepId)
        if (existing) {
          existing.status = (data?.status === 'error' ? 'error' : 'success') as ExecutionStep['status']
          existing.endTime = ts
          if (typeof data?.duration === 'number') existing.duration = data.duration
          existing.data = { request: existing.data?.request, response: data?.tool_output ?? data?.result }
        }
      }
    } else if (type === 'model_input') {
      const stepId = genId('model_io')
      if (runId) modelMap.set(runId, stepId)
      const modelName = (data?.model_name as string | undefined) ?? 'unknown'
      const provider = (data?.model_provider as string | undefined) ?? 'unknown'
      steps.push({
        id: stepId,
        nodeId: nodeName ?? 'model',
        nodeLabel: `${provider}/${modelName}`,
        stepType: 'model_io',
        title: `Model I/O (${provider}/${modelName})`,
        status: 'running',
        startTime: ts,
        data: { messages: data?.messages, model_name: modelName, model_provider: provider },
        ...traceFields,
      })
    } else if (type === 'model_output') {
      const modelName = (data?.model_name as string | undefined) ?? 'unknown'
      const provider = (data?.model_provider as string | undefined) ?? 'unknown'
      const existingId = runId ? modelMap.get(runId) : undefined
      if (existingId) {
        modelMap.delete(runId!)
        const existing = steps.find((s) => s.id === existingId)
        if (existing) {
          existing.status = 'success'
          existing.endTime = ts
          existing.data = { ...existing.data, output: data?.output }
          existing.promptTokens = data?.prompt_tokens as number | undefined
          existing.completionTokens = data?.completion_tokens as number | undefined
          existing.totalTokens = data?.total_tokens as number | undefined
        }
      } else {
        steps.push({
          id: genId('model_output'),
          nodeId: nodeName ?? 'model',
          nodeLabel: `${provider}/${modelName}`,
          stepType: 'model_io',
          title: `Model Output (${provider}/${modelName})`,
          status: 'success',
          startTime: ts,
          data: { output: data?.output, model_name: modelName, model_provider: provider },
          ...traceFields,
        })
      }
    } else if (type === 'content' || type === 'assistant_text') {
      const delta = (data?.delta as string | undefined) ?? (data?.text as string | undefined) ?? ''
      if (delta) {
        steps.push({
          id: genId('thought'),
          nodeId: nodeName ?? 'agent',
          nodeLabel: nodeName ?? 'Agent',
          stepType: 'agent_thought',
          title: `Reasoning (${nodeName ?? 'Agent'})`,
          status: 'running',
          startTime: ts,
          content: delta,
          ...traceFields,
        })
      }
    } else if (type === 'error') {
      const msg = (data?.message as string | undefined) ?? 'Unknown error'
      steps.push({
        id: genId('error'),
        nodeId: nodeName ?? 'system',
        nodeLabel: 'Error',
        stepType: 'system_log',
        title: 'Error',
        status: 'error',
        startTime: ts,
        content: msg,
        ...traceFields,
      })
    }
  }
  return steps
}

/**
 * Inner component that reads collapsedIds from the selection context
 * and feeds them into the data provider.
 */
function ExecutionTabInner({
  steps,
  isExecuting,
}: {
  steps: ExecutionStep[]
  isExecuting: boolean
}) {
  const { collapsedIds } = useExecutionSelection()
  const { roots: treeRoots, nodeMap } = useMemo(() => buildExecutionTree(steps), [steps])

  return (
    <ExecutionDataProvider
      steps={steps}
      treeRoots={treeRoots}
      nodeMap={nodeMap}
      isExecuting={isExecuting}
      collapsedIds={collapsedIds}
    >
      <ExecutionViewPreferencesProvider>
        <div className="flex h-[520px] max-h-[60vh] gap-0 overflow-hidden rounded-md border border-[var(--border)]">
          <div className="w-2/5 min-w-0 border-r border-[var(--border)]">
            <ExecutionTree />
          </div>
          <div className="flex-1 min-w-0">
            <ExecutionDetailPanel />
          </div>
        </div>
      </ExecutionViewPreferencesProvider>
    </ExecutionDataProvider>
  )
}

export default function RunDetailPage() {
  const params = useParams<{ runId: string }>()
  const runId = String(params?.runId || '')
  const { t } = useTranslation()
  const cancelRunMutation = useCancelRun()
  const runWsClientRef = useRef(getRunWsClient())

  const [run, setRun] = useState<RunSummary | null>(null)
  const [snapshot, setSnapshot] = useState<RunSnapshot | null>(null)
  const [events, setEvents] = useState<RunEvent[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [subscriptionAfterSeq, setSubscriptionAfterSeq] = useState<number | null>(null)

  useEffect(() => {
    if (!runId) return

    let cancelled = false
    setIsLoading(true)
    setLoadError(null)
    setSubscriptionAfterSeq(null)

    void Promise.all([
      runService.getRun(runId),
      runService.getRunSnapshot(runId),
      runService.getRunEvents(runId, { afterSeq: 0, limit: 500 }),
    ])
      .then(([runData, snapshotData, eventsData]) => {
        if (cancelled) return
        setRun(runData)
        setSnapshot(snapshotData)
        setEvents(eventsData.events)
        setSubscriptionAfterSeq(
          Math.max(runData.last_seq, snapshotData.last_seq, eventsData.next_after_seq),
        )
      })
      .catch((error) => {
        if (cancelled) return
        setLoadError(error instanceof Error ? error.message : 'Failed to load run details')
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [runId])

  useEffect(() => {
    if (!runId || subscriptionAfterSeq === null) {
      return
    }

    void runWsClientRef.current.subscribe(runId, subscriptionAfterSeq, {
      onSnapshot: (frame: RunSnapshotFrame) => {
        setSnapshot((current) => ({
          run_id: frame.run_id,
          status:
            typeof frame.data?.status === 'string'
              ? frame.data.status
              : current?.status || 'running',
          last_seq: frame.last_seq,
          projection: frame.data,
        }))
        setRun((current) =>
          current
            ? {
                ...current,
                status: typeof frame.data?.status === 'string' ? frame.data.status : current.status,
                last_seq: frame.last_seq,
                thread_id:
                  typeof frame.data?.thread_id === 'string'
                    ? frame.data.thread_id
                    : current.thread_id,
              }
            : current,
        )
      },
      onEvent: (frame: RunEventFrame) => {
        setEvents((current) => {
          if (current.some((item) => item.seq === frame.seq)) {
            return current
          }
          return [
            ...current,
            {
              seq: frame.seq,
              event_type: frame.event_type,
              payload: frame.data,
              trace_id: frame.trace_id,
              observation_id: frame.observation_id,
              parent_observation_id: frame.parent_observation_id,
              created_at: frame.created_at || new Date().toISOString(),
            },
          ].sort((left, right) => left.seq - right.seq)
        })
        setRun((current) =>
          current
            ? {
                ...current,
                last_seq: Math.max(current.last_seq, frame.seq),
                updated_at: frame.created_at || new Date().toISOString(),
                error_message:
                  frame.event_type === 'error' && typeof frame.data?.message === 'string'
                    ? frame.data.message
                    : current.error_message,
              }
            : current,
        )
      },
      onStatus: (frame: RunStatusFrame) => {
        setRun((current) =>
          current
            ? {
                ...current,
                status: frame.status,
                error_code: frame.error_code ?? current.error_code,
                error_message: frame.error_message ?? current.error_message,
                updated_at: new Date().toISOString(),
              }
            : current,
        )
        setSnapshot((current) =>
          current
            ? {
                ...current,
                status: frame.status,
              }
            : current,
        )
      },
      onError: (message) => {
        setLoadError(message)
      },
    })

    return () => {
      runWsClientRef.current.unsubscribe(runId)
    }
  }, [runId, subscriptionAfterSeq])

  const primaryHref = useMemo(() => (run ? buildPrimaryHref(run) : null), [run])
  const isActive = run ? ACTIVE_RUN_STATUSES.has(run.status) : false
  const executionSteps = useMemo(() => runEventsToExecutionSteps(events), [events])

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-6 py-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Button asChild variant="ghost" size="sm" className="px-2">
                <Link href="/runs" aria-label={t('execution.backToList')}>
                  <ArrowLeft className="h-4 w-4" />
                </Link>
              </Button>
              <Activity className="h-5 w-5 text-[var(--skill-brand-600)]" />
              <h1 className="text-lg font-semibold text-[var(--text-primary)]">
                {run?.title || t('execution.detailTitle')}
              </h1>
            </div>
            <p className="mt-1 text-sm text-[var(--text-muted)]">{runId}</p>
          </div>

          {run && (
            <div className="flex items-center gap-2">
              {primaryHref && (
                <Button asChild variant="outline" size="sm">
                  <Link href={primaryHref}>{t('execution.open')}</Link>
                </Button>
              )}
              {isActive && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => cancelRunMutation.mutate(run.run_id)}
                  disabled={cancelRunMutation.isPending}
                  className="gap-1.5"
                >
                  {cancelRunMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Square className="h-3.5 w-3.5" />
                  )}
                  {t('execution.cancel')}
                </Button>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('execution.loading')}
          </div>
        ) : loadError ? (
          <Card className="border-[var(--status-error-border)] bg-[var(--status-error-bg)] p-6 text-sm text-[var(--status-error)]">
            {loadError}
          </Card>
        ) : !run ? (
          <Card className="border-dashed border-[var(--border)] bg-[var(--surface-1)] p-8 text-center text-sm text-[var(--text-muted)]">
            {t('execution.emptyDescription')}
          </Card>
        ) : (
          <div className="space-y-6">
            <div className="grid gap-4 lg:grid-cols-4">
              <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4">
                <div className="mb-2 flex items-center gap-2">
                  <Bot className="h-4 w-4 text-[var(--skill-brand-600)]" />
                  <span className="text-sm font-medium text-[var(--text-secondary)]">
                    {t('execution.statusLabel')}
                  </span>
                </div>
                <Badge
                  variant="outline"
                  className="border-[var(--skill-brand-200)] bg-[var(--skill-brand-50)] text-[var(--skill-brand-700)]"
                >
                  {formatRunStatus(run.status, t)}
                </Badge>
              </Card>

              <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4">
                <div className="mb-2 flex items-center gap-2">
                  <Clock3 className="h-4 w-4 text-[var(--skill-brand-600)]" />
                  <span className="text-sm font-medium text-[var(--text-secondary)]">
                    {t('execution.startedAt')}
                  </span>
                </div>
                <div className="text-sm text-[var(--text-primary)]">
                  {formatDateTime(run.started_at)}
                </div>
              </Card>

              <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4">
                <div className="mb-2 flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-[var(--skill-brand-600)]" />
                  <span className="text-sm font-medium text-[var(--text-secondary)]">
                    {t('execution.lastSeq')}
                  </span>
                </div>
                <div className="text-sm text-[var(--text-primary)]">{run.last_seq}</div>
              </Card>

              <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4">
                <div className="mb-2 flex items-center gap-2">
                  <Activity className="h-4 w-4 text-[var(--skill-brand-600)]" />
                  <span className="text-sm font-medium text-[var(--text-secondary)]">
                    {t('execution.typeLabel')}
                  </span>
                </div>
                <div className="text-sm text-[var(--text-primary)]">{run.run_type}</div>
              </Card>
            </div>

            <Tabs defaultValue="events" className="flex flex-col gap-4">
              <TabsList className="w-fit">
                <TabsTrigger value="events">{t('execution.eventsTab')}</TabsTrigger>
                <TabsTrigger value="snapshot">{t('execution.snapshotTab')}</TabsTrigger>
                <TabsTrigger value="overview">{t('execution.overviewTab')}</TabsTrigger>
                <TabsTrigger value="execution">Execution</TabsTrigger>
              </TabsList>

              <TabsContent value="events" className="mt-0">
                <Card className="border-[var(--border)] bg-[var(--surface-1)]">
                  <ScrollArea className="h-[520px] max-h-[60vh]">
                    <div className="space-y-3 p-4">
                      {events.length === 0 ? (
                        <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--surface-2)] p-6 text-sm text-[var(--text-muted)]">
                          {t('execution.noEvents')}
                        </div>
                      ) : (
                        events.map((event) => (
                          <div
                            key={event.seq}
                            className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3"
                          >
                            <div className="mb-2 flex flex-wrap items-center gap-2">
                              <Badge variant="outline">#{event.seq}</Badge>
                              <Badge variant="outline" className="text-xs">
                                {event.event_type}
                              </Badge>
                              <span className="text-xs text-[var(--text-muted)]">
                                {formatDateTime(event.created_at)}
                              </span>
                            </div>
                            <pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs text-[var(--text-secondary)]">
                              {renderEventPayload(event.payload)}
                            </pre>
                          </div>
                        ))
                      )}
                    </div>
                  </ScrollArea>
                </Card>
              </TabsContent>

              <TabsContent value="snapshot" className="mt-0">
                <Card className="border-[var(--border)] bg-[var(--surface-1)]">
                  <ScrollArea className="h-[520px] max-h-[60vh]">
                    <pre className="p-4 text-xs text-[var(--text-secondary)]">
                      {JSON.stringify(snapshot?.projection || {}, null, 2)}
                    </pre>
                  </ScrollArea>
                </Card>
              </TabsContent>

              <TabsContent value="overview" className="mt-0">
                <div className="space-y-4">
                  <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4">
                    <dl className="grid gap-4 lg:grid-cols-2">
                      <div>
                        <dt className="text-xs text-[var(--text-muted)]">Run ID</dt>
                        <dd className="mt-1 break-all text-sm text-[var(--text-primary)]">
                          {run.run_id}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs text-[var(--text-muted)]">{t('execution.typeLabel')}</dt>
                        <dd className="mt-1 text-sm text-[var(--text-primary)]">{run.run_type}</dd>
                      </div>
                      <div>
                        <dt className="text-xs text-[var(--text-muted)]">{t('execution.startedAt')}</dt>
                        <dd className="mt-1 text-sm text-[var(--text-primary)]">
                          {formatDateTime(run.started_at)}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs text-[var(--text-muted)]">{t('execution.finishedAt')}</dt>
                        <dd className="mt-1 text-sm text-[var(--text-primary)]">
                          {formatDateTime(run.finished_at)}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs text-[var(--text-muted)]">
                          {t('execution.lastHeartbeat')}
                        </dt>
                        <dd className="mt-1 text-sm text-[var(--text-primary)]">
                          {formatDateTime(run.last_heartbeat_at)}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs text-[var(--text-muted)]">Thread ID</dt>
                        <dd className="mt-1 break-all text-sm text-[var(--text-primary)]">
                          {run.thread_id || '-'}
                        </dd>
                      </div>
                      <div className="lg:col-span-2">
                        <dt className="text-xs text-[var(--text-muted)]">Graph ID</dt>
                        <dd className="mt-1 break-all text-sm text-[var(--text-primary)]">
                          {run.graph_id || '-'}
                        </dd>
                      </div>
                      <div className="lg:col-span-2">
                        <dt className="text-xs text-[var(--text-muted)]">{t('execution.errorLabel')}</dt>
                        <dd className="mt-1 text-sm text-[var(--text-primary)]">
                          {run.error_message || '-'}
                        </dd>
                      </div>
                    </dl>
                  </Card>

                  {snapshot?.projection &&
                    (snapshot.projection as Record<string, unknown>).run_type === 'chat_turn' && (
                      <ChatTurnOverview
                        projection={snapshot.projection as Record<string, unknown>}
                        t={t}
                      />
                    )}
                  {snapshot?.projection &&
                    (snapshot.projection as Record<string, unknown>).run_type ===
                      'copilot_turn' && (
                      <CopilotTurnOverview
                        projection={snapshot.projection as unknown as CopilotTurnProjection}
                        t={t}
                      />
                    )}
                </div>
              </TabsContent>

              <TabsContent value="execution" className="mt-0">
                {executionSteps.length > 0 ? (
                  <ExecutionSelectionProvider>
                    <ExecutionTabInner steps={executionSteps} isExecuting={isActive} />
                  </ExecutionSelectionProvider>
                ) : (
                  <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--surface-2)] p-6 text-sm text-[var(--text-muted)]">
                    No execution data available
                  </div>
                )}
              </TabsContent>
            </Tabs>
          </div>
        )}
      </div>
    </div>
  )
}
