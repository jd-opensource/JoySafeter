import { describe, expect, it } from 'vitest'

import { getCopilotInputFromSearchParams } from '../useCopilotEffects'

describe('getCopilotInputFromSearchParams', () => {
  it('returns the already-decoded URLSearchParams value without decoding again', () => {
    const params = new URLSearchParams()
    params.set('copilotInput', 'Reach 95% accuracy')

    expect(getCopilotInputFromSearchParams(params)).toBe('Reach 95% accuracy')
  })
})
