import { describe, expect, it } from 'vitest'

import {
  getBuilderSurfaceKind,
  isBuilderSurfaceKind,
  type BuilderSurfaceKind,
} from '../builder-surface-registry'

describe('builder surface registry', () => {
  it.each<[string | null | undefined, BuilderSurfaceKind]>([
    ['graph', 'visual'],
    ['code', 'code'],
    ['prompt', 'prompt'],
    ['cli', 'cli'],
    ['unknown', 'visual'],
    [null, 'visual'],
    [undefined, 'visual'],
  ])('maps definition kind %s to builder surface %s', (definitionKind, expected) => {
    expect(getBuilderSurfaceKind(definitionKind)).toBe(expected)
  })

  it('recognizes only supported builder surface kinds', () => {
    expect(isBuilderSurfaceKind('visual')).toBe(true)
    expect(isBuilderSurfaceKind('cli')).toBe(true)
    expect(isBuilderSurfaceKind('spreadsheet')).toBe(false)
  })
})
