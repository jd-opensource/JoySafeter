import { describe, expect, it } from 'vitest'

import { networkPolicyRefetchInterval } from './network-policy-refresh'

describe('network policy refresh lifecycle', () => {
  it.each([
    [{ sessionActive: true, streamForced: false, networkingStatus: 'ready' }, 2000],
    [{ sessionActive: false, streamForced: true, networkingStatus: 'ready' }, 2000],
    [{ sessionActive: false, streamForced: false, networkingStatus: 'pending' }, 5000],
    [{ sessionActive: false, streamForced: false, networkingStatus: 'nacked' }, 5000],
    [{ sessionActive: false, streamForced: false, networkingStatus: 'failed' }, 5000],
    [{ sessionActive: false, streamForced: false, networkingStatus: 'ready' }, false],
    [{ sessionActive: false, streamForced: false, networkingStatus: 'disabled' }, false],
    [{ sessionActive: false, streamForced: false, networkingStatus: null }, false],
  ] as const)('returns the lifecycle interval for %o', (input, expected) => {
    expect(networkPolicyRefetchInterval(input)).toBe(expected)
  })
})
