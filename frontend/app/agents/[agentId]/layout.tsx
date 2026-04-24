'use client'

import { ArrowLeft, Bot, Loader2, Plus, MessageSquare } from 'lucide-react'
import Link from 'next/link'
import { useParams, useSearchParams } from 'next/navigation'
import { useEffect } from 'react'

import { AgentStatusIndicator } from '@/components/agents/agent-status'
import { Button } from '@/components/ui/button'
import { useAgent } from '@/hooks/queries/agents'
import { useVersion } from '@/hooks/queries/agentVersions'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { WorkspacePermissionsProvider } from '@/providers/workspace-permissions-provider'
import { useSidebarStore } from '@/stores/sidebar/store'

type TabKey = 'overview' | 'chat' | 'builder' | 'settings'

export default function AgentDetailLayout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation()
  const params = useParams()
  const searchParams = useSearchParams()
  const agentId = params.agentId as string

  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: agent, isLoading } = useAgent(agentId, workspaceId)

  const draftVersionId = agent?.current_draft_version_id || ''
  const { data: draftVersion } = useVersion(agentId, draftVersionId, workspaceId, {
    enabled: Boolean(draftVersionId),
  })

  const isGraphAgent = draftVersion?.definition_kind === 'graph'
  const tabKeys: TabKey[] = isGraphAgent
    ? ['overview', 'builder', 'chat', 'settings']
    : ['overview', 'chat', 'settings']

  const currentTab = (searchParams.get('tab') as TabKey) || 'overview'
  const basePath = `/agents/${agentId}`

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-muted)]">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        {t('common.loading')}
      </div>
    )
  }

  if (!agent) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <p className="text-sm text-[var(--text-muted)]">Agent not found</p>
        <Button variant="outline" size="sm" asChild>
          <Link href="/agents">Back to Agents</Link>
        </Button>
      </div>
    )
  }

  return (
    <WorkspacePermissionsProvider workspaceId={workspaceId}>
      <div className="flex h-full flex-col bg-[var(--bg)]">
        {/* Header - Ultra Compact Single Line */}
        <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-2 transition-all">
          
          {/* Left: Identity (flex-1 to allow middle centering if needed, but min-w-0 for truncation) */}
          <div className="flex flex-1 items-center gap-3 min-w-0 pr-4">
            <Button variant="ghost" size="sm" asChild className="-ml-2 h-8 w-8 p-0 text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
              <Link href="/agents">
                <ArrowLeft className="h-4 w-4" />
              </Link>
            </Button>
            <Bot className="h-4 w-4 shrink-0 text-[var(--skill-brand-600)]" />
            <h1 className="truncate text-sm font-semibold text-[var(--text-primary)]">
              {agent.name}
            </h1>
            <AgentStatusIndicator status={agent.status} className="shrink-0 scale-75 origin-left" />
          </div>

          {/* Middle: Tab Navigation */}
          <nav className="flex shrink-0 items-center gap-1 bg-[var(--surface-2)] p-0.5 rounded-lg border border-[var(--border)]">
            {tabKeys.map((tab) => {
              const href = tab === 'overview' ? basePath : `${basePath}?tab=${tab}`
              const isActive = currentTab === tab
              return (
                <Link
                  key={tab}
                  href={href}
                  className={cn(
                    'rounded-md px-3 py-1 text-xs font-medium transition-all',
                    isActive
                      ? 'bg-[var(--surface-elevated)] text-[var(--text-primary)] shadow-sm'
                      : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]',
                  )}
                >
                  {t(`agents.detail.tabs.${tab}`)}
                </Link>
              )
            })}
          </nav>

          {/* Right: Actions */}
          <div className="flex flex-1 items-center justify-end gap-2 pl-4">
            {currentTab !== 'builder' && (
              <>
                <Button variant="ghost" size="sm" asChild className="h-7 px-2 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
                  <Link href={`/agents/${agentId}?tab=chat`}>
                    <MessageSquare className="mr-1.5 h-3 w-3" />
                    {t('agents.detail.startChat')}
                  </Link>
                </Button>
                <Button size="sm" asChild className="h-7 px-3 text-xs">
                  <Link href={`/tasks?agent=${agentId}`}>
                    <Plus className="mr-1.5 h-3 w-3" />
                    {t('agents.detail.assignTask')}
                  </Link>
                </Button>
              </>
            )}
          </div>
        </div>

        {/* Content */}
        <div className={cn('flex-1', currentTab === 'builder' ? 'overflow-hidden' : 'overflow-y-auto')}>
          {children}
        </div>
      </div>
    </WorkspacePermissionsProvider>
  )
}
