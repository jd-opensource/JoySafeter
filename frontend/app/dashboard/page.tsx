'use client'

import { ActiveAgents } from '@/components/dashboard/active-agents'
import { DashboardEmptyState } from '@/components/dashboard/empty-state'
import { NeedsAttention } from '@/components/dashboard/needs-attention'
import { RecentTasks } from '@/components/dashboard/recent-tasks'
import { useAgents } from '@/hooks/queries/agents'
import { useTasks } from '@/hooks/queries/tasks'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { useTranslation } from '@/lib/i18n'

export default function DashboardPage() {
  const { t } = useTranslation()
  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: agents = [], isLoading: agentsLoading } = useAgents(workspaceId)
  const { data: tasks = [], isLoading: tasksLoading } = useTasks(workspaceId)

  if (agentsLoading || tasksLoading) return null

  if (agents.length === 0) return <DashboardEmptyState />

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-6 py-4">
        <h1 className="text-lg font-semibold text-[var(--text-primary)]">
          {t('dashboard.welcome', { name: '' })}
        </h1>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        {/* Top: NeedsAttention (1/3) + RecentTasks (2/3) */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="lg:col-span-1">
            <NeedsAttention workspaceId={workspaceId} tasks={tasks} />
          </div>
          <div className="lg:col-span-2">
            <RecentTasks workspaceId={workspaceId} tasks={tasks} />
          </div>
        </div>

        {/* Bottom: ActiveAgents full-width */}
        <div className="mt-4">
          <ActiveAgents workspaceId={workspaceId} agents={agents} tasks={tasks} />
        </div>
      </div>
    </div>
  )
}
