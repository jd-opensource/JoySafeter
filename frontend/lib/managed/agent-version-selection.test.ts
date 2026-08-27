import { describe, expect, it } from 'vitest'

import { advanceAgentVersionSelection } from './agent-version-selection'

describe('advanceAgentVersionSelection', () => {
  it('advances selectors that still follow the previous latest version', () => {
    expect(
      advanceAgentVersionSelection({
        previousLatest: 5,
        currentLatest: 6,
        selectedVersion: '5',
        baseVersion: '4',
        targetVersion: '5',
      }),
    ).toEqual({ selectedVersion: '6', baseVersion: '5', targetVersion: '6' })
  })

  it('keeps explicitly selected historical versions pinned', () => {
    expect(
      advanceAgentVersionSelection({
        previousLatest: 5,
        currentLatest: 6,
        selectedVersion: '3',
        baseVersion: '2',
        targetVersion: '4',
      }),
    ).toEqual({ selectedVersion: '3', baseVersion: '2', targetVersion: '4' })
  })
})
