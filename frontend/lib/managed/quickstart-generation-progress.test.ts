import { describe, expect, it } from 'vitest'

import {
  inferQuickstartGenerationPhase,
  quickstartGenerationPhaseForElapsed,
} from './quickstart-generation-progress'

describe('quickstart generation progress', () => {
  it('advances through all six professional generation phases', () => {
    expect(quickstartGenerationPhaseForElapsed(0)).toBe('understanding')
    expect(quickstartGenerationPhaseForElapsed(2)).toBe('responsibilities')
    expect(quickstartGenerationPhaseForElapsed(5)).toBe('boundaries')
    expect(quickstartGenerationPhaseForElapsed(8)).toBe('tools')
    expect(quickstartGenerationPhaseForElapsed(11)).toBe('instructions')
    expect(quickstartGenerationPhaseForElapsed(14)).toBe('acceptance')
  })

  it('uses partial blueprint evidence to advance without regressing', () => {
    expect(
      inferQuickstartGenerationPhase({
        elapsedSeconds: 1,
        agentConfig: { blueprint: { boundaries: ['Never deploy'] } },
      }),
    ).toBe('boundaries')
    expect(
      inferQuickstartGenerationPhase({
        elapsedSeconds: 3,
        agentConfig: {
          blueprint: {
            acceptance_test: { message: 'Review this diff', checks: ['Includes evidence'] },
          },
        },
      }),
    ).toBe('acceptance')
  })
})
