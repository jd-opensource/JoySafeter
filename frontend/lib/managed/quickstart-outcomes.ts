import type { QuickstartTrialStatus } from './quickstart-trial-status'

export type QuickstartOutcomeId = 'understand' | 'design' | 'protect' | 'prove'
export type QuickstartOutcomeStatus = 'complete' | 'complete_with_gaps' | 'active' | 'pending'

export interface QuickstartOutcome {
  id: QuickstartOutcomeId
  ordinal: number
  status: QuickstartOutcomeStatus
}

function activeOutcomeForStep(currentStep: number): QuickstartOutcomeId {
  if (currentStep <= 2) return 'understand'
  if (currentStep === 3) return 'design'
  if (currentStep <= 5) return 'protect'
  return 'prove'
}

export function deriveQuickstartOutcomes({
  currentStep,
  completedSteps,
  skippedSteps = new Set<number>(),
  trialStatus,
}: {
  currentStep: number
  completedSteps: Set<number>
  skippedSteps?: Set<number>
  trialStatus: QuickstartTrialStatus
}): QuickstartOutcome[] {
  const activeOutcome = activeOutcomeForStep(currentStep)
  const completed: Record<QuickstartOutcomeId, boolean> = {
    understand: completedSteps.has(1) && completedSteps.has(2),
    design: completedSteps.has(3),
    protect: completedSteps.has(4) && completedSteps.has(5),
    prove: trialStatus === 'response_received',
  }

  const protectionReviewed = [4, 5].every(
    (step) => completedSteps.has(step) || skippedSteps.has(step),
  )
  const protectionHasGaps = [4, 5].some((step) => skippedSteps.has(step))

  return (['understand', 'design', 'protect', 'prove'] as const).map((id, index) => {
    let status: QuickstartOutcomeStatus = completed[id]
      ? 'complete'
      : id === activeOutcome
        ? 'active'
        : 'pending'
    if (id === 'protect' && protectionReviewed) {
      status = protectionHasGaps ? 'complete_with_gaps' : 'complete'
    }
    return { id, ordinal: index + 1, status }
  })
}
