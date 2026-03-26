import { describe, expect, it } from 'vitest'

import { buildRunHref } from '../runHelpers'

describe('buildRunHref', () => {
  it('routes by agent_name for skill creator runs', () => {
    expect(
      buildRunHref({
        run_id: 'run-123',
        run_type: 'generic_agent',
        agent_name: 'skill_creator',
      }),
    ).toBe('/skills/creator?run=run-123')
  })
})
