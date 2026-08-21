import { describe, expect, it } from 'vitest'

import en from './locales/en'
import zh from './locales/zh'

describe('organization and project access terminology', () => {
  it('keeps organization membership and project access as separate concepts', () => {
    expect(en.translation.nav.members).toBe('Organization Members')
    expect(zh.translation.nav.members).toBe('组织成员')

    expect(en.translation.manage.members.title).toBe('Organization Members')
    expect(zh.translation.manage.members.title).toBe('组织成员')
    expect(en.translation.manage.members.role).toBe('Organization Role')
    expect(zh.translation.manage.members.role).toBe('组织角色')

    expect(en.translation.manage.projectMembers.title).toBe('Project Access')
    expect(zh.translation.manage.projectMembers.title).toBe('项目访问权限')
    expect(en.translation.manage.projectMembers.access).toBe('Project Permission')
    expect(zh.translation.manage.projectMembers.access).toBe('项目权限')
  })

  it('uses scoped role and lifecycle labels', () => {
    expect(en.translation.manage.members.roleOwner).toBe('Organization Owner')
    expect(zh.translation.manage.members.roleOwner).toBe('组织所有者')
    expect(en.translation.manage.members.roleAdmin).toBe('Organization Admin')
    expect(zh.translation.manage.members.roleAdmin).toBe('组织管理员')
    expect(en.translation.manage.members.roleMember).toBe('Organization Member')
    expect(zh.translation.manage.members.roleMember).toBe('组织成员')

    expect(en.translation.manage.projectMembers.roleAdmin).toBe('Project Admin')
    expect(zh.translation.manage.projectMembers.roleAdmin).toBe('项目管理员')
    expect(en.translation.manage.projectMembers.remove).toBe('Revoke Project Access')
    expect(zh.translation.manage.projectMembers.remove).toBe('撤销项目权限')
  })

  it('does not expose a viewer role at organization scope', () => {
    expect('roleViewer' in en.translation.manage.members).toBe(false)
    expect('roleViewer' in zh.translation.manage.members).toBe(false)
  })
})
