import { describe, expect, it } from 'vitest'

import { deriveQuickstartOutcomes } from './quickstart-outcomes'

describe('deriveQuickstartOutcomes', () => {
  it('groups six resource milestones into four user outcomes', () => {
    expect(
      deriveQuickstartOutcomes({
        currentStep: 4,
        completedSteps: new Set([1, 2, 3]),
        trialStatus: 'idle',
      }),
    ).toEqual([
      { id: 'understand', ordinal: 1, status: 'complete' },
      { id: 'design', ordinal: 2, status: 'complete' },
      { id: 'protect', ordinal: 3, status: 'active' },
      { id: 'prove', ordinal: 4, status: 'pending' },
    ])
  })

  it('does not mark Prove complete until acceptance evidence is received', () => {
    expect(
      deriveQuickstartOutcomes({
        currentStep: 6,
        completedSteps: new Set([1, 2, 3, 4, 5, 6]),
        trialStatus: 'testing',
      }).at(-1)?.status,
    ).toBe('active')

    expect(
      deriveQuickstartOutcomes({
        currentStep: 6,
        completedSteps: new Set([1, 2, 3, 4, 5, 6]),
        trialStatus: 'response_received',
      }).at(-1)?.status,
    ).toBe('complete')
  })

  it('marks Protect as reviewed with gaps when optional controls were explicitly skipped', () => {
    expect(
      deriveQuickstartOutcomes({
        currentStep: 6,
        completedSteps: new Set([1, 2, 3]),
        skippedSteps: new Set([4, 5]),
        trialStatus: 'idle',
      }),
    ).toContainEqual({ id: 'protect', ordinal: 3, status: 'complete_with_gaps' })
  })
})
