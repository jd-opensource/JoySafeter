import { describe, expect, it } from 'vitest'

import en from './locales/en'
import zh from './locales/zh'

describe('organization and project access terminology', () => {
  it('keeps organization membership and project access as separate concepts', () => {
    expect(en.translation.nav.organization).toBe('Organizations')
    expect(en.translation.manage.organization.title).toBe('Organizations')
    expect('members' in en.translation.nav).toBe(false)
    expect('members' in zh.translation.nav).toBe(false)

    expect(en.translation.manage.members.title).toBe('Members & Roles')
    expect(zh.translation.manage.members.title).toBe('成员与角色')
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

  it('describes the real add-member lifecycle instead of implying an email invitation', () => {
    expect(en.translation.manage.members.add).toBe('Add Existing User')
    expect(zh.translation.manage.members.add).toBe('添加已有用户')
    expect(en.translation.manage.members.addDescription).toContain('registered account')
    expect(zh.translation.manage.members.addDescription).toContain('已注册账号')
    expect(en.translation.manage.members.addFailed).toBe('Failed to add organization member')
    expect(zh.translation.manage.members.addFailed).toBe('添加组织成员失败')
    expect('invite' in en.translation.manage.members).toBe(false)
    expect('invite' in zh.translation.manage.members).toBe(false)
    expect(en.translation.manage.members.accessExplanation).not.toMatch(/invite/i)
    expect(zh.translation.manage.members.accessExplanation).not.toContain('邀请')
    expect(zh.translation.manage.organization.detail.tabs.overview).toBe('概览与设置')
    expect(zh.translation.manage.organization.detail.tabs.members).toBe('成员与角色')
    expect('tabs' in zh.translation.manage.organization).toBe(false)
  })
})
