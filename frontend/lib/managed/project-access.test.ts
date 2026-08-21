import { describe, expect, it } from 'vitest'

import { canManageProjectAccess, effectiveProjectAccessValue } from './project-access'

describe('project access presentation', () => {
  it('fails closed to viewer for an explicit grant without a valid role', () => {
    expect(effectiveProjectAccessValue('explicit', null)).toBe('viewer')
    expect(effectiveProjectAccessValue('explicit', 'unknown')).toBe('viewer')
  })

  it('preserves explicit roles and non-grant states', () => {
    expect(effectiveProjectAccessValue('explicit', 'admin')).toBe('admin')
    expect(effectiveProjectAccessValue('explicit', 'editor')).toBe('editor')
    expect(effectiveProjectAccessValue('none', 'admin')).toBe('none')
    expect(effectiveProjectAccessValue('org_wide', null)).toBe('org_wide')
  })

  it('presents implicit Default-project access as viewer access', () => {
    expect(effectiveProjectAccessValue('default', null)).toBe('viewer')
  })

  it('allows project access management only with effective project admin capability', () => {
    expect(canManageProjectAccess('admin')).toBe(true)
    expect(canManageProjectAccess('write')).toBe(false)
    expect(canManageProjectAccess('read')).toBe(false)
    expect(canManageProjectAccess(undefined)).toBe(false)
  })
})
