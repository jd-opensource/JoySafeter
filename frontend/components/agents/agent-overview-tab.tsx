'use client'

import { MessageSquare, Activity, Settings, GitBranch, PenTool, LayoutDashboard } from 'lucide-react'
import Link from 'next/link'
import { useMemo } from 'react'

import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { useAgent } from '@/hooks/queries/agents'
import { useAgentRuns } from '@/hooks/queries/agentRuns'
import { useReleases } from '@/hooks/queries/agentReleases'
import { useVersion } from '@/hooks/queries/agentVersions'
import { useThreads } from '@/hooks/queries/threads'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { useTranslation } from '@/lib/i18n'
import { formatRelativeTime } from '@/lib/utils/dateHelpers'
import { RUN_STATUS_STYLES } from '@/types/agent-run'
import { hasBuilderSupport } from '@/types/agent'

interface AgentOverviewTabProps {
  agentId: string
}

export function AgentOverviewTab({ agentId }: AgentOverviewTabProps) {
  const { t } = useTranslation()
  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: agent } = useAgent(agentId, workspaceId)
  const draftVersionId = agent?.current_draft_version_id || ''
  const { data: draftVersion } = useVersion(agentId, draftVersionId, workspaceId, {
    enabled: Boolean(draftVersionId),
  })
  const isGraphAgent = hasBuilderSupport(draftVersion?.definition_kind)

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

  // Merge runs and threads into a single recent activity list, sorted by time
  const activities = useMemo(() => {
    type ActivityItem =
      | { kind: 'run'; id: string; label: string; status: string; time: string }
      | { kind: 'thread'; id: string; label: string; status: string; time: string }

    const items: ActivityItem[] = [
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
    return items
      .filter((a) => a.time)
      .sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())
      .slice(0, 8)
  }, [recentRuns, recentThreads, t])

  if (!agent) return null

  return (
    <div className="grid gap-6 px-8 py-6 md:grid-cols-3 lg:grid-cols-4">
      {/* Left Column (Main Content) */}
      <div className="space-y-6 md:col-span-2 lg:col-span-3">
        {/* About / Profile Card */}
        <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5 shadow-sm transition-all hover:shadow-md">
          <div className="mb-4 flex items-center gap-2">
            <LayoutDashboard className="h-4 w-4 text-[var(--skill-brand-600)]" />
            <h2 className="text-base font-semibold text-[var(--text-primary)]">
              {t('agents.detail.about')}
            </h2>
          </div>
          <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
            {agent.description || t('agents.detail.noDescription', { defaultValue: 'No description provided for this agent.' })}
          </p>
        </Card>

        {/* Recent Activity Card */}
        <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <Activity className="h-4 w-4 text-[var(--brand-600)]" />
            <h2 className="text-base font-semibold text-[var(--text-primary)]">
              {t('agents.detail.recentActivity')}
            </h2>
          </div>
          
          {activities.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[var(--border)] py-8">
              <Activity className="mb-2 h-8 w-8 text-[var(--border)]" />
              <p className="text-sm text-[var(--text-muted)]">
                {t('agents.detail.noActivity')}
              </p>
            </div>
          ) : (
            <div className="space-y-2.5">
              {activities.map((item) => {
                const href =
                  item.kind === 'run'
                    ? `/agents/${agentId}/runs/${item.id}`
                    : `/agents/${agentId}?tab=chat&thread=${item.id}`

                return (
                  <Link
                    key={`${item.kind}-${item.id}`}
                    href={href}
                    className="group flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 transition-all hover:border-[var(--brand-300)] hover:bg-[var(--surface-3)] hover:shadow-sm"
                  >
                    <div className="flex items-center gap-3">
                      <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[var(--surface-3)] group-hover:bg-[var(--surface-4)]">
                        {item.kind === 'run' ? (
                          <GitBranch className="h-4 w-4 text-[var(--text-secondary)] group-hover:text-[var(--text-primary)]" />
                        ) : (
                          <MessageSquare className="h-4 w-4 text-[var(--text-secondary)] group-hover:text-[var(--text-primary)]" />
                        )}
                      </div>
                      <span className="truncate text-sm font-medium text-[var(--text-primary)] transition-colors group-hover:text-[var(--brand-600)]">
                        {item.label}
                      </span>
                      {item.kind === 'run' && (
                        <Badge
                          variant="outline"
                          className={cn(RUN_STATUS_STYLES[item.status] || '', "ml-2")}
                        >
                          {item.status}
                        </Badge>
                      )}
                    </div>
                    <span className="flex-shrink-0 text-xs text-[var(--text-muted)]">
                      {formatRelativeTime(item.time, t)}
                    </span>
                  </Link>
                )
              })}
            </div>
          )}
        </Card>
      </div>

      {/* Right Column (Sidebar / Stats) */}
      <div className="space-y-6 md:col-span-1">
        {/* Quick Actions */}
        <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5 shadow-sm">
          <h3 className="mb-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            {t('agents.detail.quickActions', { defaultValue: 'Quick Actions' })}
          </h3>
          <div className="flex flex-col gap-2">
            {isGraphAgent && (
              <Link
                href={`/agents/${agentId}?tab=builder`}
                className="group flex items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 transition-all hover:border-[var(--brand-400)] hover:bg-[var(--surface-3)]"
              >
                <div className="flex h-8 w-8 items-center justify-center rounded bg-[var(--skill-brand-100)] text-[var(--skill-brand-600)] transition-transform group-hover:scale-105">
                  <PenTool className="h-4 w-4" />
                </div>
                <div className="flex flex-col">
                  <span className="text-sm font-medium text-[var(--text-primary)]">
                    {t('agents.detail.openBuilder', { defaultValue: 'Open Builder' })}
                  </span>
                  <span className="text-xs text-[var(--text-muted)]">
                    {t('agents.detail.openBuilderDesc', { defaultValue: 'Edit graph configuration' })}
                  </span>
                </div>
              </Link>
            )}
            
            <Link
              href={`/agents/${agentId}?tab=settings`}
              className="group flex items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 transition-all hover:border-[var(--brand-400)] hover:bg-[var(--surface-3)]"
            >
              <div className="flex h-8 w-8 items-center justify-center rounded bg-[var(--surface-3)] text-[var(--text-secondary)] transition-transform group-hover:scale-105 group-hover:text-[var(--text-primary)]">
                <Settings className="h-4 w-4" />
              </div>
              <div className="flex flex-col">
                <span className="text-sm font-medium text-[var(--text-primary)]">
                  {t('agents.detail.settings', { defaultValue: 'Settings' })}
                </span>
                <span className="text-xs text-[var(--text-muted)]">
                  {t('agents.detail.settingsDesc', { defaultValue: 'Manage agent configuration' })}
                </span>
              </div>
            </Link>
          </div>
        </Card>

        {/* Stats & Metrics */}
        <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5 shadow-sm">
          <h3 className="mb-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            {t('agents.detail.metrics', { defaultValue: 'Usage Metrics' })}
          </h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col rounded-lg bg-[var(--surface-2)] p-3">
              <span className="text-xs text-[var(--text-muted)]">
                {t('agents.detail.totalRuns', { defaultValue: 'Total Runs' })}
              </span>
              <span className="mt-1 text-2xl font-bold text-[var(--text-primary)]">
                {allRuns.length}
              </span>
            </div>
            <div className="flex flex-col rounded-lg bg-[var(--surface-2)] p-3">
              <span className="text-xs text-[var(--text-muted)]">
                {t('agents.detail.totalThreads', { defaultValue: 'Threads' })}
              </span>
              <span className="mt-1 text-2xl font-bold text-[var(--text-primary)]">
                {threads.length}
              </span>
            </div>
          </div>
          
          <div className="mt-4 flex flex-col gap-1 border-t border-[var(--border)] pt-4 text-xs">
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">{t('agents.detail.createdAt')}</span>
              <span className="font-medium text-[var(--text-secondary)]">
                {new Date(agent.created_at).toLocaleDateString()}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">{t('agents.detail.updatedAt')}</span>
              <span className="font-medium text-[var(--text-secondary)]">
                {new Date(agent.updated_at).toLocaleDateString()}
              </span>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
