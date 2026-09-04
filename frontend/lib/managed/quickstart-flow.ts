import type { QuickstartPhase } from './quickstart-recommendation-contract'

export type QuickstartStepId = 1 | 2 | 3 | 4 | 5 | 6

export const QUICKSTART_STEP = {
  ENGINE: 1,
  MODEL_CONNECTION: 2,
  AGENT: 3,
  ENVIRONMENT: 4,
  CREDENTIAL_GROUP: 5,
  SESSION: 6,
} as const satisfies Record<string, QuickstartStepId>

export type QuickstartResourceStepId =
  | typeof QUICKSTART_STEP.AGENT
  | typeof QUICKSTART_STEP.ENVIRONMENT
  | typeof QUICKSTART_STEP.CREDENTIAL_GROUP
  | typeof QUICKSTART_STEP.SESSION

export type QuickstartCreatedResourceStepId = Exclude<
  QuickstartResourceStepId,
  typeof QUICKSTART_STEP.SESSION
>

export type QuickstartOptionalStepId =
  | typeof QUICKSTART_STEP.ENVIRONMENT
  | typeof QUICKSTART_STEP.CREDENTIAL_GROUP

export interface QuickstartPhaseDefinition {
  id: QuickstartPhase
  ordinal: number
  steps: readonly QuickstartStepId[]
}

export const QUICKSTART_PHASE_DEFINITIONS: readonly QuickstartPhaseDefinition[] = [
  {
    id: 'understand',
    ordinal: 1,
    steps: [QUICKSTART_STEP.ENGINE, QUICKSTART_STEP.MODEL_CONNECTION],
  },
  { id: 'design', ordinal: 2, steps: [QUICKSTART_STEP.AGENT] },
  {
    id: 'secure',
    ordinal: 3,
    steps: [QUICKSTART_STEP.ENVIRONMENT, QUICKSTART_STEP.CREDENTIAL_GROUP],
  },
  { id: 'prove', ordinal: 4, steps: [QUICKSTART_STEP.SESSION] },
]

export const QUICKSTART_PHASE_BY_STEP = Object.fromEntries(
  QUICKSTART_PHASE_DEFINITIONS.flatMap((phase) =>
    phase.steps.map((step) => [step, phase.id] as const),
  ),
) as Readonly<Record<QuickstartStepId, QuickstartPhase>>

export const QUICKSTART_DESIGN_STEP = QUICKSTART_STEP.AGENT

export interface QuickstartFlowProgress {
  currentStep: QuickstartStepId
  completedSteps: Set<number>
  skippedSteps: Set<number>
}

export type QuickstartFlowAction =
  | { type: 'scope_changed'; hasEngine: boolean }
  | { type: 'engine_selected' }
  | { type: 'model_connection_selected' }
  | { type: 'complete'; step: QuickstartStepId; advance?: boolean }
  | { type: 'skip'; step: QuickstartOptionalStepId }
  | { type: 'advance' }
  | { type: 'go_to'; step: QuickstartStepId }
  | { type: 'reopen'; step: QuickstartStepId }

export const INITIAL_QUICKSTART_PROGRESS: QuickstartFlowProgress = {
  currentStep: QUICKSTART_STEP.ENGINE,
  completedSteps: new Set(),
  skippedSteps: new Set(),
}

function nextStep(step: QuickstartStepId): QuickstartStepId {
  return Math.min(step + 1, QUICKSTART_STEP.SESSION) as QuickstartStepId
}

export function reduceQuickstartFlow(
  state: QuickstartFlowProgress,
  action: QuickstartFlowAction,
): QuickstartFlowProgress {
  switch (action.type) {
    case 'scope_changed':
      return {
        currentStep: action.hasEngine ? QUICKSTART_STEP.MODEL_CONNECTION : QUICKSTART_STEP.ENGINE,
        completedSteps: action.hasEngine ? new Set([QUICKSTART_STEP.ENGINE]) : new Set(),
        skippedSteps: new Set(),
      }
    case 'engine_selected':
      return {
        currentStep: QUICKSTART_STEP.MODEL_CONNECTION,
        completedSteps: new Set([...state.completedSteps, QUICKSTART_STEP.ENGINE]),
        skippedSteps: state.skippedSteps,
      }
    case 'model_connection_selected':
      return {
        currentStep: QUICKSTART_DESIGN_STEP,
        completedSteps: new Set([
          ...state.completedSteps,
          QUICKSTART_STEP.ENGINE,
          QUICKSTART_STEP.MODEL_CONNECTION,
        ]),
        skippedSteps: state.skippedSteps,
      }
    case 'complete': {
      const skippedSteps = new Set(state.skippedSteps)
      skippedSteps.delete(action.step)
      return {
        currentStep: action.advance === false ? state.currentStep : nextStep(action.step),
        completedSteps: new Set([...state.completedSteps, action.step]),
        skippedSteps,
      }
    }
    case 'skip': {
      const completedSteps = new Set(state.completedSteps)
      completedSteps.delete(action.step)
      return {
        currentStep: nextStep(Math.max(state.currentStep, action.step) as QuickstartStepId),
        completedSteps,
        skippedSteps: new Set([...state.skippedSteps, action.step]),
      }
    }
    case 'advance':
      return { ...state, currentStep: nextStep(state.currentStep) }
    case 'go_to':
      return { ...state, currentStep: action.step }
    case 'reopen':
      return {
        currentStep: action.step,
        completedSteps: new Set([...state.completedSteps].filter((step) => step < action.step)),
        skippedSteps: new Set([...state.skippedSteps].filter((step) => step < action.step)),
      }
  }
}

export function quickstartPhaseForStep(step: QuickstartStepId): QuickstartPhase {
  return QUICKSTART_PHASE_BY_STEP[step]
}

export function quickstartStepsForPhase(phase: QuickstartPhase): readonly QuickstartStepId[] {
  return QUICKSTART_PHASE_DEFINITIONS.find((definition) => definition.id === phase)?.steps ?? []
}
