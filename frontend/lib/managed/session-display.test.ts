import { describe, expect, it } from 'vitest'

import { getSessionDisplayTitle } from './session-display'

describe('getSessionDisplayTitle', () => {
  it('prefers a trimmed persisted title', () => {
    expect(getSessionDisplayTitle('  Research Agent · 08-10 08:05  ', 'Untitled session')).toBe(
      'Research Agent · 08-10 08:05',
    )
  })

  it.each([undefined, null, '', '   '])('uses the fallback for legacy empty titles', (title) => {
    expect(getSessionDisplayTitle(title, 'Untitled session')).toBe('Untitled session')
  })
})
