'use client'

import {
  Activity,
  ArrowLeft,
  Bot,
  Clock3,
  Loader2,
  Sparkles,
  Square,
} from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCancelRun } from '@/hooks/queries/runs'
import { useTranslation } from '@/lib/i18n'
import { ACTIVE_RUN_STATUSES, buildRunHref, formatRunStatus } from '@/lib/utils/runHelpers'
import { getRunWsClient } from '@/lib/ws/runs/runWsClient'
import type { RunEventFrame, RunSnapshotFrame, RunStatusFrame } from '@/lib/ws/runs/types'
import type { RunEvent, RunSnapshot, RunSummary } from '@/services/runService'
import { runService } from '@/services/runService'

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
    tool_calls?: Array<{ id?: string; name: string; status: string; args?: Record<string, unknown>; result?: string }>
  }
  file_tree?: Record<string, { action: string; size?: number; timestamp?: number }>
  preview_data?: Record<string, unknown>
  node_execution_log?: Array<{ status: string; node_name: string }>
}

function ChatTurnOverview({ projection: p, t }: { projection: Record<string, unknown>; t: (key: string, fallback: string) => string }) {
  const projection = p as unknown as ChatTurnProjection
  return (
    <div className="space-y-4">
      {projection.user_message && (
        <Card className="p-4">
          <h4 className="text-sm font-medium text-muted-foreground mb-2">{t('runs.chat.userMessage', 'User Message')}</h4>
          <p className="text-sm whitespace-pre-wrap">{projection.user_message.content}</p>
        </Card>
      )}

      {projection.assistant_message && (
        <Card className="p-4">
          <h4 className="text-sm font-medium text-muted-foreground mb-2">{t('runs.chat.assistantResponse', 'Assistant Response')}</h4>
          <p className="text-sm whitespace-pre-wrap">{projection.assistant_message.content}</p>

          {projection.assistant_message.tool_calls && projection.assistant_message.tool_calls.length > 0 && (
            <div className="mt-3 space-y-2">
              <h5 className="text-xs font-medium text-muted-foreground">{t('runs.chat.toolCalls', 'Tool Calls')}</h5>
              {projection.assistant_message.tool_calls.map((tool, i) => (
                <details key={tool.id || i} className="text-xs border rounded p-2">
                  <summary className="cursor-pointer font-medium">
                    {tool.name} — {tool.status}
                  </summary>
                  {tool.args && (
                    <pre className="mt-1 text-muted-foreground overflow-x-auto">
                      {JSON.stringify(tool.args, null, 2)}
                    </pre>
                  )}
                  {tool.result && (
                    <pre className="mt-1 text-muted-foreground overflow-x-auto">
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
          <h4 className="text-sm font-medium text-muted-foreground mb-2">{t('runs.chat.files', 'Files')}</h4>
          <ul className="text-xs space-y-1">
            {Object.entries(projection.file_tree).map(([path, info]) => (
              <li key={path} className="flex items-center gap-2">
                <Badge variant="outline" className="text-[10px]">{info.action}</Badge>
                <span className="font-mono truncate">{path}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {projection.preview_data && (
        <Card className="p-4">
          <h4 className="text-sm font-medium text-muted-foreground mb-2">{t('runs.chat.preview', 'Preview')}</h4>
          <pre className="text-xs overflow-x-auto">
            {JSON.stringify(projection.preview_data, null, 2)}
          </pre>
        </Card>
      )}

      {projection.node_execution_log && projection.node_execution_log.length > 0 && (
        <Card className="p-4">
          <h4 className="text-sm font-medium text-muted-foreground mb-2">{t('runs.chat.executionLog', 'Execution Log')}</h4>
          <ul className="text-xs space-y-1">
            {projection.node_execution_log.map((entry, i) => (
              <li key={i} className="flex items-center gap-2">
                <Badge variant={entry.status === 'completed' ? 'default' : 'secondary'} className="text-[10px]">
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

function CopilotTurnOverview({ projection, t }: { projection: CopilotTurnProjection; t: (key: string, fallback: string) => string }) {

  return (
    <div className="space-y-4">
      {/* Stage indicator */}
      {projection.stage && (
        <div className="rounded-md border p-3">
          <p className="text-sm font-medium">{t('runs.stage', 'Stage')}</p>
          <p className="text-sm text-muted-foreground">{projection.stage}</p>
        </div>
      )}

      {/* Mode */}
      {projection.mode && (
        <div className="rounded-md border p-3">
          <p className="text-sm font-medium">{t('runs.mode', 'Mode')}</p>
          <p className="text-sm text-muted-foreground">{projection.mode}</p>
        </div>
      )}

      {/* Content */}
      {projection.content && (
        <div className="rounded-md border p-3">
          <p className="text-sm font-medium">{t('runs.content', 'Content')}</p>
          <p className="mt-1 whitespace-pre-wrap text-sm">{projection.content}</p>
        </div>
      )}

      {/* Thought Steps (collapsible) */}
      {projection.thought_steps && projection.thought_steps.length > 0 && (
        <details className="rounded-md border p-3">
          <summary className="cursor-pointer text-sm font-medium">
            {t('runs.thoughtSteps', 'Thought Steps')} ({projection.thought_steps.length})
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
            {t('runs.toolCalls', 'Tool Calls')} ({projection.tool_calls.length})
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
        <div className="rounded-md border border-green-200 bg-green-50 p-3 dark:border-green-800 dark:bg-green-950">
          <p className="text-sm font-medium">{t('runs.result', 'Result')}</p>
          <p className="mt-1 whitespace-pre-wrap text-sm">{projection.result_message}</p>
          {projection.result_actions && projection.result_actions.length > 0 && (
            <div className="mt-2">
              <p className="text-xs font-medium text-muted-foreground">
                {projection.result_actions.length} action(s)
              </p>
              {projection.result_actions.map((action, i) => (
                <div key={i} className="mt-1 text-xs text-muted-foreground">
                  {action.type}{action.reasoning ? ` — ${action.reasoning}` : ''}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {projection.error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 dark:border-red-800 dark:bg-red-950">
          <p className="text-sm font-medium text-red-700 dark:text-red-400">{t('runs.error', 'Error')}</p>
          <p className="mt-1 text-sm text-red-600 dark:text-red-300">{projection.error}</p>
        </div>
      )}
    </div>
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
          status: typeof frame.data?.status === 'string' ? frame.data.status : current?.status || 'running',
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
                  typeof frame.data?.thread_id === 'string' ? frame.data.thread_id : current.thread_id,
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

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-6 py-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Button asChild variant="ghost" size="sm" className="px-2">
                <Link href="/runs">
                  <ArrowLeft className="h-4 w-4" />
                </Link>
              </Button>
              <Activity className="h-5 w-5 text-[var(--skill-brand-600)]" />
              <h1 className="text-lg font-semibold text-[var(--text-primary)]">
                {run?.title || t('runs.detailTitle', 'Run Details')}
              </h1>
            </div>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              {runId}
            </p>
          </div>

          {run && (
            <div className="flex items-center gap-2">
              {primaryHref && (
                <Button asChild variant="outline" size="sm">
                  <Link href={primaryHref}>{t('runs.open', 'Open')}</Link>
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
                  {t('runs.cancel', 'Cancel')}
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
            {t('runs.loading', 'Loading runs...')}
          </div>
        ) : loadError ? (
          <Card className="border-red-200 bg-red-50 p-6 text-sm text-red-600 dark:border-red-800 dark:bg-red-950 dark:text-red-400">
            {loadError}
          </Card>
        ) : !run ? (
          <Card className="border-dashed border-[var(--border)] bg-[var(--surface-1)] p-8 text-center text-sm text-[var(--text-muted)]">
            {t('runs.emptyDescription', 'Long-running agent tasks will appear here once they start.')}
          </Card>
        ) : (
          <div className="space-y-6">
            <div className="grid gap-4 lg:grid-cols-4">
              <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4">
                <div className="mb-2 flex items-center gap-2">
                  <Bot className="h-4 w-4 text-[var(--skill-brand-600)]" />
                  <span className="text-sm font-medium text-[var(--text-secondary)]">
                    {t('runs.statusLabel', 'Status')}
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
                    {t('runs.startedAt', 'Started')}
                  </span>
                </div>
                <div className="text-sm text-[var(--text-primary)]">{formatDateTime(run.started_at)}</div>
              </Card>

              <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4">
                <div className="mb-2 flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-[var(--skill-brand-600)]" />
                  <span className="text-sm font-medium text-[var(--text-secondary)]">
                    {t('runs.lastSeq', 'Last Seq')}
                  </span>
                </div>
                <div className="text-sm text-[var(--text-primary)]">{run.last_seq}</div>
              </Card>

              <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4">
                <div className="mb-2 flex items-center gap-2">
                  <Activity className="h-4 w-4 text-[var(--skill-brand-600)]" />
                  <span className="text-sm font-medium text-[var(--text-secondary)]">
                    {t('runs.typeLabel', 'Type')}
                  </span>
                </div>
                <div className="text-sm text-[var(--text-primary)]">{run.run_type}</div>
              </Card>
            </div>

            <Tabs defaultValue="events" className="flex flex-col gap-4">
              <TabsList className="w-fit">
                <TabsTrigger value="events">{t('runs.eventsTab', 'Events')}</TabsTrigger>
                <TabsTrigger value="snapshot">{t('runs.snapshotTab', 'Snapshot')}</TabsTrigger>
                <TabsTrigger value="overview">{t('runs.overviewTab', 'Overview')}</TabsTrigger>
              </TabsList>

              <TabsContent value="events" className="mt-0">
                <Card className="border-[var(--border)] bg-[var(--surface-1)]">
                  <ScrollArea className="h-[520px]">
                    <div className="space-y-3 p-4">
                      {events.length === 0 ? (
                        <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--surface-2)] p-6 text-sm text-[var(--text-muted)]">
                          {t('runs.noEvents', 'No events recorded yet.')}
                        </div>
                      ) : (
                        events.map((event) => (
                          <div
                            key={event.seq}
                            className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3"
                          >
                            <div className="mb-2 flex flex-wrap items-center gap-2">
                              <Badge variant="outline">#{event.seq}</Badge>
                              <Badge variant="outline" className="text-[10px]">
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
                  <ScrollArea className="h-[520px]">
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
                        <dd className="mt-1 break-all text-sm text-[var(--text-primary)]">{run.run_id}</dd>
                      </div>
                      <div>
                        <dt className="text-xs text-[var(--text-muted)]">{t('runs.typeLabel', 'Type')}</dt>
                        <dd className="mt-1 text-sm text-[var(--text-primary)]">{run.run_type}</dd>
                      </div>
                      <div>
                        <dt className="text-xs text-[var(--text-muted)]">{t('runs.startedAt', 'Started')}</dt>
                        <dd className="mt-1 text-sm text-[var(--text-primary)]">{formatDateTime(run.started_at)}</dd>
                      </div>
                      <div>
                        <dt className="text-xs text-[var(--text-muted)]">{t('runs.finishedAt', 'Finished')}</dt>
                        <dd className="mt-1 text-sm text-[var(--text-primary)]">{formatDateTime(run.finished_at)}</dd>
                      </div>
                      <div>
                        <dt className="text-xs text-[var(--text-muted)]">{t('runs.lastHeartbeat', 'Heartbeat')}</dt>
                        <dd className="mt-1 text-sm text-[var(--text-primary)]">
                          {formatDateTime(run.last_heartbeat_at)}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs text-[var(--text-muted)]">Thread ID</dt>
                        <dd className="mt-1 break-all text-sm text-[var(--text-primary)]">{run.thread_id || '-'}</dd>
                      </div>
                      <div className="lg:col-span-2">
                        <dt className="text-xs text-[var(--text-muted)]">Graph ID</dt>
                        <dd className="mt-1 break-all text-sm text-[var(--text-primary)]">{run.graph_id || '-'}</dd>
                      </div>
                      <div className="lg:col-span-2">
                        <dt className="text-xs text-[var(--text-muted)]">{t('runs.errorLabel', 'Error')}</dt>
                        <dd className="mt-1 text-sm text-[var(--text-primary)]">{run.error_message || '-'}</dd>
                      </div>
                    </dl>
                  </Card>

                  {snapshot?.projection && (snapshot.projection as Record<string, unknown>).run_type === 'chat_turn' && (
                    <ChatTurnOverview projection={snapshot.projection as Record<string, unknown>} t={t} />
                  )}
                  {snapshot?.projection && (snapshot.projection as Record<string, unknown>).run_type === 'copilot_turn' && (
                    <CopilotTurnOverview projection={snapshot.projection as unknown as CopilotTurnProjection} t={t} />
                  )}
                </div>
              </TabsContent>
            </Tabs>
          </div>
        )}
      </div>
    </div>
  )
}
