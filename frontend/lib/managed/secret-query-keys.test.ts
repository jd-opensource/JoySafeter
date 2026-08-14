import { describe, expect, it } from 'vitest'

import { secretDetailQueryKey } from './secret-query-keys'

describe('Secret query keys', () => {
  it('includes the catalog version after the stable Secret identity prefix', () => {
    expect(
      secretDetailQueryKey(
        'org-a:project-a',
        'secret_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020',
        '2026-08-07.2',
      ),
    ).toEqual([
      'secret',
      'org-a:project-a',
      'secret_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020',
      '2026-08-07.2',
    ])
  })
})
