'use client'

import { MessageSquare, Plus, Activity } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useAgent } from '@/hooks/queries/agents'
import { useAgentRuns } from '@/hooks/queries/agentRuns'
import { useReleases } from '@/hooks/queries/agentReleases'
import { useThreads } from '@/hooks/queries/threads'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { useTranslation } from '@/lib/i18n'
import { RUN_STATUS_STYLES } from '@/types/agent-run'

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

interface AgentOverviewTabProps {
  agentId: string
}

export function AgentOverviewTab({ agentId }: AgentOverviewTabProps) {
  const { t } = useTranslation()
  const router = useRouter()

  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: agent } = useAgent(agentId, workspaceId)

  const { data: releases = [] } = useReleases(agentId, workspaceId, {
    enabled: Boolean(workspaceId),
  })
  const releaseIds = new Set(releases.map((r) => r.id))

  const { data: allRuns = [] } = useAgentRuns(
    { workspace_id: workspaceId },
    { enabled: Boolean(workspaceId) },
  )
  const recentRuns = allRuns.filter((run) => releaseIds.has(run.release_id)).slice(0, 5)

  const { data: threads = [] } = useThreads(agentId, workspaceId)
  const recentThreads = threads.slice(0, 5)

  if (!agent) return null

  // Merge runs and threads into a single recent activity list, sorted by time
  type ActivityItem =
    | { kind: 'run'; id: string; label: string; status: string; time: string }
    | { kind: 'thread'; id: string; label: string; status: string; time: string }

  const activities: ActivityItem[] = [
    ...recentRuns.map((run) => ({
      kind: 'run' as const,
      id: run.id,
      label: run.goal || t('execution.untitled'),
      status: run.status,
      time: run.started_at || run.created_at || '',
    })),
    ...recentThreads.map((thread) => ({
      kind: 'thread' as const,
      id: thread.id,
      label: thread.title || t('execution.untitled'),
      status: thread.status,
      time: thread.created_at,
    })),
  ]
    .filter((a) => a.time)
    .sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())
    .slice(0, 8)

  return (
    <div className="space-y-8 px-8 py-6">
      {/* Description */}
      <p className="text-sm text-[var(--text-secondary)]">
        {agent.description || t('agents.detail.noActivity')}
      </p>

      {/* Action Buttons */}
      <div className="flex items-center gap-3">
        <Button asChild>
          <Link href={`/tasks?agent=${agentId}`}>
            <Plus className="mr-1.5 h-4 w-4" />
            {t('agents.detail.assignTask')}
          </Link>
        </Button>
        <Button
          variant="outline"
          onClick={() => router.push(`/agents/${agentId}?tab=chat`)}
        >
          <MessageSquare className="mr-1.5 h-4 w-4" />
          {t('agents.detail.startChat')}
        </Button>
      </div>

      {/* Recent Activity */}
      <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
        <h2 className="mb-3 text-sm font-semibold text-[var(--text-primary)]">
          {t('agents.detail.recentActivity')}
        </h2>
        {activities.length === 0 ? (
          <p className="text-sm text-[var(--text-muted)]">
            {t('agents.detail.noActivity')}
          </p>
        ) : (
          <div className="space-y-2">
            {activities.map((item) => {
              const href =
                item.kind === 'run'
                  ? `/agents/${agentId}/runs/${item.id}`
                  : `/agents/${agentId}?tab=chat&thread=${item.id}`

              return (
                <Link
                  key={`${item.kind}-${item.id}`}
                  href={href}
                  className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 transition-colors hover:bg-[var(--surface-3)]"
                >
                  <div className="flex items-center gap-2">
                    {item.kind === 'run' ? (
                      <Activity className="h-3.5 w-3.5 text-[var(--text-muted)]" />
                    ) : (
                      <MessageSquare className="h-3.5 w-3.5 text-[var(--text-muted)]" />
                    )}
                    <span className="truncate text-sm text-[var(--text-primary)]">
                      {item.label}
                    </span>
                    {item.kind === 'run' && (
                      <Badge
                        variant="outline"
                        className={RUN_STATUS_STYLES[item.status] || ''}
                      >
                        {item.status}
                      </Badge>
                    )}
                  </div>
                  <span className="flex-shrink-0 text-xs text-[var(--text-muted)]">
                    {formatRelativeTime(item.time)}
                  </span>
                </Link>
              )
            })}
          </div>
        )}
      </Card>
    </div>
  )
}
