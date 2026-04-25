'use client'

import { useEffect, useState } from 'react'

import { useTranslation } from '@/lib/i18n'
import type { Agent } from '@/types/agent'

import { StudioStageNav } from './studio-stage-nav'
import { StudioTopBar } from './studio-top-bar'
import {
  AGENT_STUDIO_STAGES,
  getDefaultStudioStage,
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
  const stageContext = { nodesCount, hasActiveRelease: Boolean(agent.active_release_id) }
  const defaultStage = getDefaultStudioStage(stageContext)
  const [activeStage, setActiveStage] = useState<AgentStudioStage>(() =>
    normalizeStudioStage(initialStage, stageContext),
  )
  const activeStageMeta = AGENT_STUDIO_STAGES.find((stage) => stage.id === activeStage)
  const defaultStageMeta = AGENT_STUDIO_STAGES.find((stage) => stage.id === defaultStage)

  useEffect(() => {
    if (!initialStage) return

    setActiveStage(
      normalizeStudioStage(initialStage, {
        nodesCount,
        hasActiveRelease: Boolean(agent.active_release_id),
      }),
    )
  }, [initialStage, nodesCount, agent.active_release_id])

  const handlePrimaryAction = () => {
    const currentIndex = AGENT_STUDIO_STAGES.findIndex((stage) => stage.id === activeStage)
    const nextStage = AGENT_STUDIO_STAGES[currentIndex + 1]?.id

    if (nextStage) {
      setActiveStage(nextStage)
    }
  }

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
        <StudioStageNav activeStage={activeStage} onStageChange={setActiveStage} />
        <main className="flex-1 p-5 md:p-8">
          <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface-1)] p-6">
            <p className="text-sm font-medium text-[var(--text-primary)]">
              {t('agents.studio.stageOverview', {
                activeStage: t(activeStageMeta?.labelKey ?? 'agents.studio.stages.brief'),
                defaultStage: t(defaultStageMeta?.labelKey ?? 'agents.studio.stages.brief'),
              })}
            </p>
            <p className="mt-2 text-sm text-[var(--text-muted)]">
              {t(
                activeStageMeta?.descriptionKey ?? 'agents.studio.stageDescriptions.brief',
              )}
            </p>
          </div>
        </main>
      </div>
    </section>
  )
}
