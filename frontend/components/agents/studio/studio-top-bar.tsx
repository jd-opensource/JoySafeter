'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'
import type { Agent } from '@/types/agent'

import type { AgentStudioStage } from './studio-types'

const PRIMARY_ACTION_BY_STAGE: Record<AgentStudioStage, string> = {
  brief: 'generateDraft',
  canvas: 'runDraft',
  'test-lab': 'runDraft',
  release: 'publish',
  usage: 'openUsage',
}

interface StudioTopBarProps {
  agent: Agent
  activeStage: AgentStudioStage
  nodesCount: number
  hasPendingChanges: boolean
  onPrimaryAction: () => void
}

export function StudioTopBar({
  agent,
  activeStage,
  nodesCount,
  hasPendingChanges,
  onPrimaryAction,
}: StudioTopBarProps) {
  const { t } = useTranslation()
  const draftStatus =
    nodesCount === 0 ? 'emptyDraft' : hasPendingChanges ? 'unsavedDraft' : 'savedDraft'
  const releaseStatus = agent.active_release_id ? 'published' : 'notPublished'

  return (
    <header className="flex flex-col gap-4 border-b border-[var(--border)] bg-[var(--surface-1)] px-5 py-4 md:flex-row md:items-center md:justify-between">
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--skill-brand-600)]">
          {t('agents.studio.visualAgent')}
        </p>
        <h1 className="mt-1 truncate text-xl font-semibold text-[var(--text-primary)]">
          {agent.name}
        </h1>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{t(`agents.studio.status.${draftStatus}`)}</Badge>
        <Badge variant={agent.active_release_id ? 'default' : 'outline'}>
          {t(`agents.studio.status.${releaseStatus}`)}
        </Badge>
        <Button type="button" onClick={onPrimaryAction}>
          {t(`agents.studio.actions.${PRIMARY_ACTION_BY_STAGE[activeStage]}`)}
        </Button>
      </div>
    </header>
  )
}
