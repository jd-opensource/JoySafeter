'use client'

import { DashboardEmptyState } from '@/components/dashboard/empty-state'
import { useAgents } from '@/hooks/queries/agents'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { useTranslation } from '@/lib/i18n'

export default function DashboardPage() {
  const { t } = useTranslation()
  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: agents = [], isLoading } = useAgents(workspaceId)

  if (isLoading) return null

  if (agents.length === 0) return <DashboardEmptyState />

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-6 py-4">
        <h1 className="text-lg font-semibold text-[var(--text-primary)]">
          {t('dashboard.title')}
        </h1>
      </div>
      {/* Data sections will be added in Task 3 */}
    </div>
  )
}
