'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

import { useTranslation } from '@/lib/i18n'
import { useCurrentWorkspace } from '@/providers/workspace-provider'
import type { Agent } from '@/types/agent'

import { StudioBriefStage } from './studio-brief-stage'
import { StudioCanvasStage } from './studio-canvas-stage'
import { StudioStageNav } from './studio-stage-nav'
import { StudioTestLabStage } from './studio-test-lab-stage'
import { StudioTopBar } from './studio-top-bar'
import {
  AGENT_STUDIO_STAGES,
  normalizeStudioStage,
  type AgentStudioStage,
} from './studio-types'

interface AgentStudioShellProps {
  agent: Agent
  initialStage?: string | null
  nodesCount: number
  hasPendingChanges?: boolean
}

export function AgentStudioShell({
  agent,
  initialStage,
  nodesCount,
  hasPendingChanges = false,
}: AgentStudioShellProps) {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const { workspaceId } = useCurrentWorkspace()
  const stageContext = { nodesCount, hasActiveRelease: Boolean(agent.active_release_id) }
  const [activeStage, setActiveStage] = useState<AgentStudioStage>(() =>
    normalizeStudioStage(initialStage, stageContext),
  )

  useEffect(() => {
    if (!initialStage) return

    setActiveStage(
      normalizeStudioStage(initialStage, {
        nodesCount,
        hasActiveRelease: Boolean(agent.active_release_id),
      }),
    )
  }, [initialStage, nodesCount, agent.active_release_id])

  const handleStageChange = useCallback(
    (stage: AgentStudioStage) => {
      setActiveStage(stage)
      const params = new URLSearchParams(searchParams.toString())
      params.set('stage', stage)
      router.replace(`/agents/${agent.id}?${params.toString()}`, { scroll: false })
    },
    [agent.id, router, searchParams],
  )

  const handlePrimaryAction = () => {
    const currentIndex = AGENT_STUDIO_STAGES.findIndex((stage) => stage.id === activeStage)
    const nextStage = AGENT_STUDIO_STAGES[currentIndex + 1]?.id

    if (nextStage) {
      handleStageChange(nextStage)
    }
  }

  const handleGenerateFromBrief = useCallback(
    (prompt: string) => {
      setActiveStage('canvas')
      const params = new URLSearchParams(searchParams.toString())
      params.set('stage', 'canvas')
      params.set('copilotInput', prompt)
      router.replace(`/agents/${agent.id}?${params.toString()}`, { scroll: false })
    },
    [agent.id, router, searchParams],
  )

  return (
    <section className="flex min-h-[640px] flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface-1)] shadow-sm">
      <StudioTopBar
        agent={agent}
        activeStage={activeStage}
        nodesCount={nodesCount}
        hasPendingChanges={hasPendingChanges}
        onPrimaryAction={handlePrimaryAction}
      />
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <StudioStageNav activeStage={activeStage} onStageChange={handleStageChange} />
        <main className="min-w-0 flex-1 overflow-hidden">
          {activeStage === 'brief' && (
            <StudioBriefStage
              agent={agent}
              onGenerate={handleGenerateFromBrief}
              onSkipToCanvas={() => handleStageChange('canvas')}
            />
          )}
          {activeStage === 'canvas' && (
            <StudioCanvasStage
              agentId={agent.id}
              workspaceId={workspaceId}
              versionId={agent.current_draft_version_id || undefined}
              onOpenTestLab={() => handleStageChange('test-lab')}
              onOpenRelease={() => handleStageChange('release')}
            />
          )}
          {activeStage === 'test-lab' && (
            <StudioTestLabStage
              agentId={agent.id}
              onOpenCanvas={() => handleStageChange('canvas')}
              onOpenRelease={() => handleStageChange('release')}
              versionId={agent.current_draft_version_id || undefined}
              workspaceId={workspaceId}
            />
          )}
          {activeStage !== 'brief' && activeStage !== 'canvas' && activeStage !== 'test-lab' && (
            <div className="flex h-full items-center justify-center p-8 text-center">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">
                  {t('agents.studio.title', { defaultValue: 'Agent Studio' })}
                </p>
                <h2 className="mt-2 text-2xl font-semibold">{activeStage}</h2>
              </div>
            </div>
          )}
        </main>
      </div>
    </section>
  )
}
