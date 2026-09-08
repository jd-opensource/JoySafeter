import {
  QUICKSTART_PHASE_DEFINITIONS,
  quickstartPhaseForStep,
  quickstartStepsForPhase,
  type QuickstartStepId,
} from './quickstart-flow'
import type { QuickstartTrialStatus } from './quickstart-trial-status'

export type QuickstartOutcomeId = 'understand' | 'design' | 'secure' | 'prove'
export type QuickstartOutcomeStatus = 'complete' | 'complete_with_gaps' | 'active' | 'pending'

export interface QuickstartOutcome {
  id: QuickstartOutcomeId
  ordinal: number
  status: QuickstartOutcomeStatus
}

function activeOutcomeForStep(currentStep: number): QuickstartOutcomeId {
  return quickstartPhaseForStep(currentStep as QuickstartStepId)
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
  const completed = Object.fromEntries(
    QUICKSTART_PHASE_DEFINITIONS.map((phase) => [
      phase.id,
      phase.id === 'prove'
        ? trialStatus === 'response_received'
        : phase.steps.every((step) => completedSteps.has(step)),
    ]),
  ) as Record<QuickstartOutcomeId, boolean>

  const securitySteps = quickstartStepsForPhase('secure')
  const securityReviewed = securitySteps.every(
    (step) => completedSteps.has(step) || skippedSteps.has(step),
  )
  const securityHasGaps = securitySteps.some((step) => skippedSteps.has(step))

  return QUICKSTART_PHASE_DEFINITIONS.map(({ id, ordinal }) => {
    let status: QuickstartOutcomeStatus = completed[id]
      ? 'complete'
      : id === activeOutcome
        ? 'active'
        : 'pending'
    if (id === 'secure' && securityReviewed) {
      status = securityHasGaps ? 'complete_with_gaps' : 'complete'
    }
    return { id, ordinal, status }
  })
}
