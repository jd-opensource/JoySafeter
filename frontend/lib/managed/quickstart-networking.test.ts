import { describe, expect, it } from 'vitest'

import { normalizeQuickstartAllowedHosts } from './quickstart-networking'

describe('normalizeQuickstartAllowedHosts', () => {
  it('normalizes configured hosts without applying recommendation heuristics', () => {
    expect(
      normalizeQuickstartAllowedHosts(
        'https://www.github.com/org/repo, api.github.com, github.com, localhost:8080, service.local, example.com',
      ),
    ).toEqual([
      'www.github.com',
      'api.github.com',
      'github.com',
      'localhost',
      'service.local',
      'example.com',
    ])
  })
})
