'use client'

import { useTranslation } from '@/lib/i18n'

export const QUICKSTART_COMPLETION_STEPS = [3, 4, 5, 6] as const

export type QuickstartCompletionStep = (typeof QUICKSTART_COMPLETION_STEPS)[number]

export function isQuickstartCompletionStep(step: number): step is QuickstartCompletionStep {
  return QUICKSTART_COMPLETION_STEPS.some((completionStep) => completionStep === step)
}

interface QuickstartCompletionCopyProps {
  step: QuickstartCompletionStep
}

interface QuickstartCompletionDescriptionProps extends QuickstartCompletionCopyProps {
  className?: string
}

export function QuickstartCompletionTitle({ step }: QuickstartCompletionCopyProps) {
  const { t } = useTranslation()

  switch (step) {
    case 3:
      return t('managed.quickstart.stepComplete.agentCreated')
    case 4:
      return t('managed.quickstart.stepComplete.envCreated')
    case 5:
      return t('managed.quickstart.stepComplete.vaultCreated')
    case 6:
      return t('managed.quickstart.stepComplete.sessionStarted')
  }
}

export function QuickstartCompletionDescription({
  step,
  className,
}: QuickstartCompletionDescriptionProps) {
  const { t } = useTranslation()
  let description: string

  switch (step) {
    case 3:
      description = t('managed.quickstart.stepDesc.agent')
      break
    case 4:
      description = t('managed.quickstart.stepDesc.environment')
      break
    case 5:
      description = t('managed.quickstart.stepDesc.mcpCredentialSet')
      break
    case 6:
      description = t('managed.quickstart.stepDesc.session')
      break
  }

  return <p className={className}>{description}</p>
}
