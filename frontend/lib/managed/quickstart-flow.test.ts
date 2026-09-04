import { describe, expect, it } from 'vitest'

import {
  INITIAL_QUICKSTART_PROGRESS,
  QUICKSTART_DESIGN_STEP,
  QUICKSTART_PHASE_DEFINITIONS,
  QUICKSTART_PHASE_BY_STEP,
  quickstartPhaseForStep,
  quickstartStepsForPhase,
  reduceQuickstartFlow,
} from './quickstart-flow'

describe('quickstart flow model', () => {
  it('keeps UI sub-steps inside one canonical four-phase model', () => {
    expect(Object.values(QUICKSTART_PHASE_BY_STEP)).toEqual([
      'understand',
      'understand',
      'design',
      'secure',
      'secure',
      'prove',
    ])
    expect(quickstartPhaseForStep(QUICKSTART_DESIGN_STEP)).toBe('design')
    expect(QUICKSTART_PHASE_DEFINITIONS.map((phase) => phase.id)).toEqual([
      'understand',
      'design',
      'secure',
      'prove',
    ])
    expect(quickstartStepsForPhase('secure')).toEqual([4, 5])
  })

  it('centralizes complete, skip, and reopen transitions', () => {
    const understood = reduceQuickstartFlow(INITIAL_QUICKSTART_PROGRESS, {
      type: 'engine_selected',
    })
    const designed = reduceQuickstartFlow(understood, { type: 'model_connection_selected' })
    const securedWithGap = reduceQuickstartFlow(designed, { type: 'skip', step: 4 })
    const reopened = reduceQuickstartFlow(securedWithGap, { type: 'reopen', step: 3 })

    expect(designed.currentStep).toBe(3)
    expect(securedWithGap.currentStep).toBe(5)
    expect(securedWithGap.skippedSteps).toEqual(new Set([4]))
    expect(reopened.completedSteps).toEqual(new Set([1, 2]))
    expect(reopened.skippedSteps).toEqual(new Set())
  })

  it('resets project-scoped progress without losing a global engine choice', () => {
    expect(
      reduceQuickstartFlow(INITIAL_QUICKSTART_PROGRESS, {
        type: 'scope_changed',
        hasEngine: true,
      }),
    ).toEqual({ currentStep: 2, completedSteps: new Set([1]), skippedSteps: new Set() })
  })
})
