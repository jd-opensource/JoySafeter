'use client'

import { AlertTriangle, Check } from 'lucide-react'

import { useTranslation } from '@/lib/i18n'
import type { QuickstartStepId } from '@/lib/managed/quickstart-flow'
import { deriveQuickstartOutcomes } from '@/lib/managed/quickstart-outcomes'
import type { QuickstartTrialStatus } from '@/lib/managed/quickstart-trial-status'
import { cn } from '@/lib/utils'

export function QuickstartOutcomeRail({
  currentStep,
  completedSteps,
  skippedSteps,
  trialStatus,
}: {
  currentStep: QuickstartStepId
  completedSteps: Set<number>
  skippedSteps: Set<number>
  trialStatus: QuickstartTrialStatus
}) {
  const { t } = useTranslation()
  const outcomes = deriveQuickstartOutcomes({
    currentStep,
    completedSteps,
    skippedSteps,
    trialStatus,
  })

  return (
    <nav
      aria-label={t('managed.quickstart.outcome.navigationLabel')}
      className="mb-2 flex items-center justify-center gap-3 py-2"
    >
      {outcomes.map((outcome, index) => {
        const isDone = outcome.status === 'complete'
        const hasGaps = outcome.status === 'complete_with_gaps'
        const isActive = outcome.status === 'active'

        return (
          <div key={outcome.id} className="flex items-center gap-3">
            {index > 0 && <span className="text-muted-foreground/50">→</span>}
            <div className="flex items-center gap-2 whitespace-nowrap">
              <span
                className={cn(
                  'flex h-6 w-6 items-center justify-center rounded-full border text-[11px] font-semibold',
                  isDone && 'border-green-500 bg-green-500 text-white',
                  hasGaps && 'border-amber-500 bg-amber-500/10 text-amber-700',
                  isActive && !isDone && !hasGaps && 'border-primary bg-primary/10 text-primary',
                  !isDone && !hasGaps && !isActive && 'border-border text-muted-foreground',
                )}
              >
                {isDone ? (
                  <Check className="h-3 w-3" />
                ) : hasGaps ? (
                  <AlertTriangle className="h-3 w-3" />
                ) : (
                  outcome.ordinal
                )}
              </span>
              <span
                className={cn(
                  'text-sm font-medium',
                  isActive || isDone || hasGaps ? 'text-foreground' : 'text-muted-foreground',
                )}
              >
                {t(`managed.quickstart.outcome.${outcome.id}.title`)}
              </span>
              {hasGaps ? (
                <span className="rounded-full bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">
                  {t('managed.quickstart.outcome.reviewedWithGaps')}
                </span>
              ) : null}
            </div>
          </div>
        )
      })}
    </nav>
  )
}
