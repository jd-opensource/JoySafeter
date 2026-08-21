import { describe, expect, it } from 'vitest'

import { DEFAULT_ORGANIZATION_ROLE, roleOptions } from './roles'

const t = (key: string) => key

describe('organization role vocabulary', () => {
  it('defaults invitations to the least-privilege valid organization role', () => {
    expect(DEFAULT_ORGANIZATION_ROLE).toBe('member')
  })

  it('never exposes legacy developer or project-only roles as organization roles', () => {
    expect(roleOptions(t).map((option) => option.value)).toEqual(['admin', 'member'])
    expect(roleOptions(t).map((option) => option.value)).not.toContain('developer')
    expect(roleOptions(t).map((option) => option.value)).not.toContain('viewer')
  })
})
