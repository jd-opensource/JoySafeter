'use client'

import { Activity, ArrowLeft, Clock, Loader2 } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ExecutionTimelineView } from '@/components/execution/ExecutionTimeline'
import { ExecutionDetailPanel } from '@/components/execution/ExecutionDetailPanel'
import { useExecution, useExecutionEvents } from '@/hooks/queries/agentRuns'
import { useCurrentWorkspace } from '@/providers/workspace-provider'
import { TERMINAL_EXECUTION_STATUSES } from '@/types/agent-run'

function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

function formatDuration(startedAt?: string | null, endedAt?: string | null): string {
  if (!startedAt) return '-'
  const end = endedAt ? new Date(endedAt) : new Date()
  const ms = end.getTime() - new Date(startedAt).getTime()
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`
}

export default function ExecutionDetailPage() {
  const params = useParams()
  const executionId = params.executionId as string

  const { workspaceId } = useCurrentWorkspace()

  const { data: execution, isLoading: isExecutionLoading } = useExecution(executionId, {
    enabled: Boolean(executionId),
  })

  const { data: events = [], isLoading: isEventsLoading } = useExecutionEvents(executionId, {
    enabled: Boolean(executionId),
  })

  const isLoading = isExecutionLoading || isEventsLoading
  const isTerminal = execution?.status && TERMINAL_EXECUTION_STATUSES.includes(execution.status)

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="sm" asChild>
              <Link href="/dashboard">
                <ArrowLeft className="h-4 w-4" />
              </Link>
            </Button>
            <Activity className="h-5 w-5 text-[var(--skill-brand-600)]" />
            <div>
              <h1 className="text-lg font-semibold text-[var(--text-primary)]">
                Execution Detail
              </h1>
              <p className="text-xs text-[var(--text-muted)]">{executionId}</p>
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading execution...
          </div>
        ) : !execution ? (
          <Card className="border-dashed border-[var(--border)] bg-[var(--surface-1)] p-8 text-center">
            <p className="text-sm text-[var(--text-muted)]">Execution not found</p>
          </Card>
        ) : (
          <div className="space-y-6">
            {/* Metadata Cards */}
            <div className="grid gap-4 lg:grid-cols-4">
              <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4">
                <div className="mb-2 flex items-center gap-2">
                  <Activity className="h-4 w-4 text-[var(--skill-brand-600)]" />
                  <span className="text-sm font-medium text-[var(--text-secondary)]">Status</span>
                </div>
                <Badge variant="outline">{execution.status}</Badge>
              </Card>

              <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4">
                <div className="mb-2 flex items-center gap-2">
                  <Clock className="h-4 w-4 text-[var(--skill-brand-600)]" />
                  <span className="text-sm font-medium text-[var(--text-secondary)]">Started</span>
                </div>
                <div className="text-sm text-[var(--text-primary)]">
                  {formatDateTime(execution.started_at)}
                </div>
              </Card>

              <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4">
                <div className="mb-2 flex items-center gap-2">
                  <Clock className="h-4 w-4 text-[var(--skill-brand-600)]" />
                  <span className="text-sm font-medium text-[var(--text-secondary)]">Duration</span>
                </div>
                <div className="text-sm text-[var(--text-primary)]">
                  {formatDuration(execution.started_at, execution.ended_at)}
                </div>
              </Card>

              <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4">
                <div className="mb-2 flex items-center gap-2">
                  <Activity className="h-4 w-4 text-[var(--skill-brand-600)]" />
                  <span className="text-sm font-medium text-[var(--text-secondary)]">Executor</span>
                </div>
                <div className="text-sm text-[var(--text-primary)]">
                  {execution.executor_kind}
                </div>
              </Card>
            </div>

            {/* Tabs */}
            <Tabs defaultValue="timeline" className="flex flex-col gap-4">
              <TabsList className="w-fit">
                <TabsTrigger value="timeline">Timeline</TabsTrigger>
                <TabsTrigger value="events">Events</TabsTrigger>
                <TabsTrigger value="metadata">Metadata</TabsTrigger>
              </TabsList>

              <TabsContent value="timeline" className="mt-0">
                <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4">
                  {events.length === 0 ? (
                    <p className="text-sm text-[var(--text-muted)]">No events yet</p>
                  ) : (
                    <ExecutionTimelineView />
                  )}
                </Card>
              </TabsContent>

              <TabsContent value="events" className="mt-0">
                <Card className="border-[var(--border)] bg-[var(--surface-1)]">
                  <ScrollArea className="h-[520px] max-h-[60vh]">
                    <div className="space-y-3 p-4">
                      {events.length === 0 ? (
                        <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--surface-2)] p-6 text-sm text-[var(--text-muted)]">
                          No events
                        </div>
                      ) : (
                        events.map((event, idx) => (
                          <div
                            key={event.id || idx}
                            className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3"
                          >
                            <div className="mb-2 flex flex-wrap items-center gap-2">
                              <Badge variant="outline" className="text-xs">
                                {event.event_type}
                              </Badge>
                              <span className="text-xs text-[var(--text-muted)]">
                                {formatDateTime(event.created_at)}
                              </span>
                            </div>
                            <pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs text-[var(--text-secondary)]">
                              {JSON.stringify(event.payload, null, 2)}
                            </pre>
                          </div>
                        ))
                      )}
                    </div>
                  </ScrollArea>
                </Card>
              </TabsContent>

              <TabsContent value="metadata" className="mt-0">
                <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4">
                  <dl className="grid gap-4 lg:grid-cols-2">
                    <div>
                      <dt className="text-xs text-[var(--text-muted)]">Execution ID</dt>
                      <dd className="mt-1 break-all text-sm text-[var(--text-primary)]">
                        {execution.id}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-[var(--text-muted)]">Run ID</dt>
                      <dd className="mt-1 break-all text-sm text-[var(--text-primary)]">
                        {execution.run_id}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-[var(--text-muted)]">Attempt Index</dt>
                      <dd className="mt-1 text-sm text-[var(--text-primary)]">
                        {execution.attempt_index}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-[var(--text-muted)]">Executor Kind</dt>
                      <dd className="mt-1 text-sm text-[var(--text-primary)]">
                        {execution.executor_kind}
                      </dd>
                    </div>
                    {execution.parent_execution_id && (
                      <div className="lg:col-span-2">
                        <dt className="text-xs text-[var(--text-muted)]">Parent Execution</dt>
                        <dd className="mt-1 break-all text-sm text-[var(--text-primary)]">
                          <Link
                            href={`/executions/${execution.parent_execution_id}`}
                            className="text-[var(--skill-brand-600)] hover:underline"
                          >
                            {execution.parent_execution_id}
                          </Link>
                        </dd>
                      </div>
                    )}
                    {execution.error && (
                      <div className="lg:col-span-2">
                        <dt className="text-xs text-[var(--text-muted)]">Error</dt>
                        <dd className="mt-1 text-sm text-[var(--status-error)]">
                          {execution.error.message}
                        </dd>
                      </div>
                    )}
                  </dl>
                </Card>
              </TabsContent>
            </Tabs>
          </div>
        )}
      </div>
    </div>
  )
}
