'use client'

import { useCallback, useState, type ReactNode } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

import { useTranslation } from '@/lib/i18n'
import { useCurrentWorkspace } from '@/providers/workspace-provider'
import type { Agent, AgentVersion } from '@/types/agent'

import { BUILD_STAGES, isBuildStageId, resolveDefaultStage, type BuildStageId } from './agent-build-types'
import { BuildStepper } from './build-stepper'
import { useBuilderSurface } from './builder-surface-context'
import { StageRenderer } from './stage-renderer'

interface AgentBuildShellProps {
  agent: Agent
  version: AgentVersion | null
}

export function AgentBuildShell({ agent, version }: AgentBuildShellProps) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const surface = useBuilderSurface()
  const { workspaceId } = useCurrentWorkspace()
  const [toolbarSlot, setToolbarSlot] = useState<ReactNode>(null)

  const [activeStageId, setActiveStageId] = useState<BuildStageId>(() => {
    const urlStage = searchParams.get('stage')
    if (urlStage && isBuildStageId(urlStage)) return urlStage
    return resolveDefaultStage(agent, version)
  })

  const navigateToStage = useCallback(
    (stageId: BuildStageId) => {
      setActiveStageId(stageId)
      const params = new URLSearchParams(searchParams.toString())
      params.set('stage', stageId)
      router.replace(`/agents/${agent.id}?${params.toString()}`, { scroll: false })
    },
    [agent.id, router, searchParams],
  )

  const stageProps = {
    agent,
    version,
    workspaceId,
    navigateToStage,
    onToolbarSlot: setToolbarSlot,
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-1">
        <BuildStepper
          stages={BUILD_STAGES}
          activeStage={activeStageId}
          onNavigate={navigateToStage}
        />
        {toolbarSlot}
      </header>
      <main className="min-h-0 flex-1 overflow-hidden">
        <StageRenderer
          stageId={activeStageId}
          surface={surface}
          stageProps={stageProps}
        />
      </main>
    </div>
  )
}
