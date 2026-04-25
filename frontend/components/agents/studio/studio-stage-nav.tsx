'use client'

import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { AGENT_STUDIO_STAGES, type AgentStudioStage } from './studio-types'

interface StudioStageNavProps {
  activeStage: AgentStudioStage
  onStageChange: (stage: AgentStudioStage) => void
}

export function StudioStageNav({ activeStage, onStageChange }: StudioStageNavProps) {
  const { t } = useTranslation()

  return (
    <nav
      aria-label={t('agents.studio.title')}
      className="flex w-full gap-2 overflow-x-auto border-b border-[var(--border)] bg-[var(--surface-1)] p-3 md:h-full md:w-64 md:flex-col md:overflow-x-visible md:border-b-0 md:border-r"
    >
      {AGENT_STUDIO_STAGES.map((stage) => {
        const Icon = stage.icon
        const isActive = stage.id === activeStage

        return (
          <button
            key={stage.id}
            type="button"
            aria-current={isActive ? 'page' : undefined}
            className={cn(
              'flex min-w-40 items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors',
              'hover:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--skill-brand-500)]',
              isActive
                ? 'bg-[var(--skill-brand-50)] text-[var(--skill-brand-700)] shadow-sm'
                : 'text-[var(--text-muted)]',
            )}
            onClick={() => onStageChange(stage.id)}
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
  )
}
