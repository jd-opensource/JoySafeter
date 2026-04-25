'use client'

import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import type { BuildStageConfig, BuildStageId } from './agent-build-types'

interface BuildStepperProps {
  stages: readonly BuildStageConfig[]
  activeStage: BuildStageId
  onNavigate: (stageId: BuildStageId) => void
}

export function BuildStepper({ stages, activeStage, onNavigate }: BuildStepperProps) {
  const { t } = useTranslation()

  return (
    <nav aria-label="Build stages" className="flex items-center gap-1">
      {stages.map((stage, index) => {
        const Icon = stage.icon
        const isActive = stage.id === activeStage
        const isLast = index === stages.length - 1

        return (
          <div key={stage.id} className="flex items-center">
            <button
              type="button"
              aria-current={isActive ? 'step' : undefined}
              className={cn(
                'flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
                'hover:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--skill-brand-600)]',
                isActive
                  ? 'bg-[var(--skill-brand-50)] text-[var(--skill-brand-700)]'
                  : 'text-[var(--text-muted)]',
              )}
              onClick={() => onNavigate(stage.id)}
            >
              <span
                className={cn(
                  'flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[10px] font-bold',
                  isActive
                    ? 'bg-[var(--skill-brand-600)] text-white'
                    : 'bg-[var(--surface-2)] text-[var(--text-muted)]',
                )}
              >
                {index + 1}
              </span>
              <Icon className="h-3.5 w-3.5 shrink-0" />
              <span className="hidden whitespace-nowrap sm:inline">{t(stage.labelKey)}</span>
            </button>
            {!isLast && (
              <div className="mx-1 h-px w-4 bg-[var(--border)]" />
            )}
          </div>
        )
      })}
    </nav>
  )
}
