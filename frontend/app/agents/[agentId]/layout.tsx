'use client'

import { ArrowLeft, Bot, Loader2 } from 'lucide-react'
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
        {/* Header */}
        <div 
          className={cn(
            "border-b border-[var(--border)] bg-[var(--surface-elevated)] transition-all",
            currentTab === 'builder' ? "flex items-center justify-between px-4 py-2" : "px-8 py-5"
          )}
        >
          <div className={cn("flex flex-col", currentTab === 'builder' ? "flex-row items-center gap-3" : "")}>
            {/* Breadcrumb */}
            {currentTab !== 'builder' && (
              <div className="mb-3 flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
                <Link href="/agents" className="hover:text-[var(--text-secondary)]">
                  {t('sidebar.agents')}
                </Link>
                <span>/</span>
                <span className="text-[var(--text-secondary)]">{agent.name}</span>
              </div>
            )}

            <div className="flex items-center gap-3">
              <Button variant="ghost" size="sm" asChild className="h-8 w-8 p-0">
                <Link href="/agents">
                  <ArrowLeft className="h-4 w-4" />
                </Link>
              </Button>
              {currentTab !== 'builder' && <Bot className="h-5 w-5 text-[var(--skill-brand-600)]" />}
              <div className="min-w-0">
                <h1 className={cn(
                  "truncate font-semibold text-[var(--text-primary)]",
                  currentTab === 'builder' ? "text-sm" : "text-lg"
                )}>
                  {agent.name}
                </h1>
              </div>
              {currentTab !== 'builder' && <AgentStatusIndicator status={agent.status} className="ml-2" />}
            </div>
          </div>

          {/* Tab navigation */}
          <nav className={cn("flex gap-1", currentTab === 'builder' ? "" : "mt-4")}>
            {tabKeys.map((tab) => {
              const href = tab === 'overview' ? basePath : `${basePath}?tab=${tab}`
              const isActive = currentTab === tab

              return (
                <Link
                  key={tab}
                  href={href}
                  className={cn(
                    'rounded-md px-4 py-2 text-sm font-medium transition-colors',
                    isActive
                      ? 'bg-[var(--surface-3)] text-[var(--text-primary)]'
                      : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]',
                    currentTab === 'builder' && 'px-3 py-1.5'
                  )}
                >
                  {t(`agents.detail.tabs.${tab}`)}
                </Link>
              )
            })}
          </nav>
        </div>

        {/* Content */}
        <div className={cn('flex-1', currentTab === 'builder' ? 'overflow-hidden' : 'overflow-y-auto')}>
          {children}
        </div>
      </div>
    </WorkspacePermissionsProvider>
  )
}
