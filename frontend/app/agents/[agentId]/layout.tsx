'use client'

import { ArrowLeft, Bot, Loader2, MessageSquare, Settings } from 'lucide-react'
import Link from 'next/link'
import { useParams, useSearchParams, useRouter } from 'next/navigation'
import {
  BUILD_STAGES,
  isBuildStageId,
  type BuildStageId,
} from '@/components/agents/agent-build/agent-build-types'
import { BuildStepper } from '@/components/agents/agent-build/build-stepper'

import { AgentStatusIndicator } from '@/components/agents/agent-status'
import { Button } from '@/components/ui/button'
import { useAgent } from '@/hooks/queries/agents'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { useProjectContext } from '@/hooks/managed/use-project-context'

export default function AgentDetailLayout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation()
  const params = useParams()
  const searchParams = useSearchParams()
  const router = useRouter()
  const agentId = params.agentId as string
  const { projectId } = useProjectContext()
  const { data: agent, isLoading } = useAgent(agentId, projectId)
  const currentTab = searchParams.get('tab')

  const activeStageId = searchParams.get('stage') as BuildStageId | null

  const navigateToStage = (stageId: BuildStageId) => {
    const params = new URLSearchParams(searchParams.toString())
    params.set('stage', stageId)
    router.replace(`/agents/${agentId}?${params.toString()}`, { scroll: false })
  }

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
        <div className="flex min-w-0 items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            asChild
            className="-ml-2 h-8 w-8 p-0 text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          >
            <Link href="/agents">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <Bot className="h-4 w-4 shrink-0 text-[var(--skill-brand-600)]" />
          <h1 className="truncate text-sm font-semibold text-[var(--text-primary)]">
            {agent.name}
          </h1>
          <AgentStatusIndicator status={agent.status} className="shrink-0 origin-left scale-75" />
        </div>

        {/* Center: Build Stepper (only in builder mode) */}
        {!currentTab && (
          <div className="hidden lg:block">
            <BuildStepper
              stages={BUILD_STAGES}
              activeStage={activeStageId && isBuildStageId(activeStageId) ? activeStageId : 'brief'}
              onNavigate={navigateToStage}
            />
          </div>
        )}

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
