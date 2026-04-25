'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import type { Agent } from '@/types/agent'

import type { AgentBuildStageConfig, AgentBuildStatusBadge } from './agent-build-types'

interface AgentBuildShellProps<TStage extends AgentBuildStageConfig = AgentBuildStageConfig> {
  agent: Agent
  stages: readonly TStage[]
  initialStage?: string | null
  defaultStage: TStage['id']
  titleKey: string
  statusBadges: readonly (AgentBuildStatusBadge | string)[]
  renderStage: (stage: TStage, navigateToStage: (stageId: TStage['id']) => void) => React.ReactNode
}

function normalizeStage<TStage extends AgentBuildStageConfig>(
  value: string | null | undefined,
  stages: readonly TStage[],
  defaultStage: TStage['id'],
): TStage['id'] {
  return stages.some((stage) => stage.id === value) ? (value as TStage['id']) : defaultStage
}

export function AgentBuildShell<TStage extends AgentBuildStageConfig>({
  agent,
  stages,
  initialStage,
  defaultStage,
  titleKey,
  statusBadges,
  renderStage,
}: AgentBuildShellProps<TStage>) {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const [activeStageId, setActiveStageId] = useState<TStage['id']>(() =>
    normalizeStage(initialStage, stages, defaultStage),
  )

  useEffect(() => {
    if (!initialStage) return
    setActiveStageId(normalizeStage(initialStage, stages, defaultStage))
  }, [defaultStage, initialStage, stages])

  const activeStage = useMemo(
    () => stages.find((stage) => stage.id === activeStageId) ?? stages[0],
    [activeStageId, stages],
  )

  const navigateToStage = useCallback(
    (stageId: TStage['id']) => {
      setActiveStageId(stageId)
      const params = new URLSearchParams(searchParams.toString())
      params.set('stage', stageId)
      router.replace(`/agents/${agent.id}?${params.toString()}`, { scroll: false })
    },
    [agent.id, router, searchParams],
  )

  const handlePrimaryAction = () => {
    const currentIndex = stages.findIndex((stage) => stage.id === activeStageId)
    const nextStage = stages[currentIndex + 1]
    if (nextStage) {
      navigateToStage(nextStage.id)
    }
  }

  const nextStageExists = stages.some(
    (stage, index) => stage.id === activeStageId && Boolean(stages[index + 1]),
  )

  return (
    <section className="flex min-h-[640px] flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface-1)] shadow-sm">
      <header className="flex flex-col gap-4 border-b border-[var(--border)] bg-[var(--surface-1)] px-5 py-4 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--skill-brand-600)]">
            {t(titleKey)}
          </p>
          <h1 className="mt-1 truncate text-xl font-semibold text-[var(--text-primary)]">
            {agent.name}
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {statusBadges.map((badge) => {
            const normalized =
              typeof badge === 'string' ? { label: badge, variant: 'outline' as const } : badge
            return (
              <Badge key={normalized.label} variant={normalized.variant ?? 'outline'}>
                {t(normalized.label)}
              </Badge>
            )
          })}
          {nextStageExists && activeStage.primaryActionKey && (
            <Button type="button" onClick={handlePrimaryAction}>
              {t(activeStage.primaryActionKey)}
            </Button>
          )}
        </div>
      </header>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <nav
          aria-label={t(titleKey)}
          className="flex w-full gap-2 overflow-x-auto border-b border-[var(--border)] bg-[var(--surface-1)] p-3 md:h-full md:w-64 md:flex-col md:overflow-x-visible md:border-b-0 md:border-r"
        >
          {stages.map((stage) => {
            const Icon = stage.icon
            const isActive = stage.id === activeStageId

            return (
              <button
                key={stage.id}
                type="button"
                aria-current={isActive ? 'page' : undefined}
                className={cn(
                  'flex min-w-40 items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors',
                  'hover:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--skill-brand-600)]',
                  isActive
                    ? 'bg-[var(--skill-brand-50)] text-[var(--skill-brand-700)] shadow-sm'
                    : 'text-[var(--text-muted)]',
                )}
                onClick={() => navigateToStage(stage.id)}
              >
                <span
                  className={cn(
                    'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border',
                    isActive
                      ? 'border-[var(--skill-brand-200)] bg-white text-[var(--skill-brand-600)]'
                      : 'border-[var(--border)] bg-[var(--surface-1)] text-[var(--text-muted)]',
                  )}
                >
                  <Icon className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold">{t(stage.labelKey)}</span>
                  <span className="block truncate text-xs text-[var(--text-muted)]">
                    {t(stage.descriptionKey)}
                  </span>
                </span>
              </button>
            )
          })}
        </nav>
        <main className="min-w-0 flex-1 overflow-hidden">
          {renderStage(activeStage, navigateToStage)}
        </main>
      </div>
    </section>
  )
}
