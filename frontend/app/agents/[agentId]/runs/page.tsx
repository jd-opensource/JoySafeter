'use client'

import { Activity, ArrowRight, Clock, Loader2 } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'

import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { useAgentRuns } from '@/hooks/queries/agentRuns'
import { useReleases } from '@/hooks/queries/agentReleases'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { useTranslation } from '@/lib/i18n'
import { RUN_STATUS_STYLES } from '@/types/agent-run'

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

export default function AgentRunsPage() {
  const params = useParams()
  const agentId = params.agentId as string
  const { t } = useTranslation()

  const { data: workspaces = [], isLoading: isWorkspacesLoading } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id ?? ''

  const { data: releases = [], isLoading: isReleasesLoading } = useReleases(agentId, workspaceId, {
    enabled: Boolean(workspaceId),
  })

  const releaseIds = new Set(releases.map((r) => r.id))

  // Fetch all workspace runs; filter client-side by release belonging to this agent
  const { data: allRuns = [], isLoading: isRunsLoading } = useAgentRuns(
    { workspace_id: workspaceId },
    { enabled: Boolean(workspaceId) },
  )

  const runs = allRuns.filter((run) => releaseIds.has(run.release_id))

  const isLoading = isWorkspacesLoading || isReleasesLoading || isRunsLoading

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-8 py-5">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-[var(--skill-brand-600)]" />
          <h2 className="text-lg font-semibold text-[var(--text-primary)]">{t('execution.title')}</h2>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-8 py-6">
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('execution.loading')}
          </div>
        ) : runs.length === 0 ? (
          <Card className="border-dashed border-[var(--border)] bg-[var(--surface-1)] p-8 text-center">
            <Activity className="mx-auto mb-3 h-8 w-8 text-[var(--text-muted)]" />
            <p className="text-sm text-[var(--text-muted)]">{t('execution.emptyTitle')}</p>
          </Card>
        ) : (
          <div className="space-y-2">
            {runs.map((run) => (
              <Link key={run.id} href={`/agents/${agentId}/runs/${run.id}`} className="block">
                <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4 transition-colors hover:bg-[var(--surface-2)]">
                  <div className="flex items-center justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <Badge
                          variant="outline"
                          className={RUN_STATUS_STYLES[run.status]}
                        >
                          {t(`execution.status${run.status.charAt(0).toUpperCase() + run.status.slice(1)}`)}
                        </Badge>
                        <Badge variant="outline" className="text-xs">
                          {run.trigger_source}
                        </Badge>
                      </div>
                      {run.goal && (
                        <p className="mt-1.5 truncate text-sm text-[var(--text-primary)]">
                          {run.goal}
                        </p>
                      )}
                      <div className="mt-1 flex items-center gap-3 text-xs text-[var(--text-muted)]">
                        <span className="flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {formatDateTime(run.started_at)}
                        </span>
                        <span>{formatDuration(run.started_at, run.ended_at)}</span>
                      </div>
                    </div>
                    <ArrowRight className="h-4 w-4 shrink-0 text-[var(--text-muted)]" />
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
