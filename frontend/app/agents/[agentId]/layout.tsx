'use client'

import { ArrowLeft, Bot, Loader2, MessageSquare, Settings } from 'lucide-react'
import Link from 'next/link'
import { useParams, useSearchParams } from 'next/navigation'

import { AgentStatusIndicator } from '@/components/agents/agent-status'
import { Button } from '@/components/ui/button'
import { useAgent } from '@/hooks/queries/agents'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { useCurrentWorkspace } from '@/providers/workspace-provider'

export default function AgentDetailLayout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation()
  const params = useParams()
  const searchParams = useSearchParams()
  const agentId = params.agentId as string
  const { workspaceId } = useCurrentWorkspace()
  const { data: agent, isLoading } = useAgent(agentId, workspaceId)
  const currentTab = searchParams.get('tab')

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
    <div className="flex h-full flex-col bg-[var(--bg)]">
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-2">
        {/* Left: Identity */}
        <div className="flex items-center gap-3 min-w-0">
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

        {/* Right: Chat + Settings */}
        <div className="flex items-center gap-1">
          <Button
            variant={currentTab === 'chat' ? 'secondary' : 'ghost'}
            size="sm"
            asChild
            className="h-7 px-2 text-xs"
          >
            <Link href={`/agents/${agentId}?tab=chat`}>
              <MessageSquare className="mr-1.5 h-3 w-3" />
              {t('agents.detail.tabs.chat', { defaultValue: 'Chat' })}
            </Link>
          </Button>
          <Button
            variant={currentTab === 'settings' ? 'secondary' : 'ghost'}
            size="sm"
            asChild
            className="h-7 px-2 text-xs"
          >
            <Link href={`/agents/${agentId}?tab=settings`}>
              <Settings className="mr-1.5 h-3 w-3" />
              {t('agents.detail.tabs.settings', { defaultValue: 'Settings' })}
            </Link>
          </Button>
        </div>
      </div>

      <div className={cn('flex-1', currentTab ? 'overflow-y-auto' : 'overflow-hidden')}>
        {children}
      </div>
    </div>
  )
}
