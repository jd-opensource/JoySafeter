import { describe, it, expect } from 'vitest'
import { graphDataAdapter } from '../graphDataAdapter'
import { visualDefinitionAdapter } from '../visualDefinitionAdapter'

describe('graphDataAdapter', () => {
  it('re-exports visualDefinitionAdapter for compatibility', () => {
    expect(graphDataAdapter).toBe(visualDefinitionAdapter)
  })
})
