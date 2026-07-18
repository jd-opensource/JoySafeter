type Translator = (key: string) => string

// ── Organization role (owner/admin/member) — answers only "am I a super-user?" ──
// Per-project write/read capability is NOT expressed here; it comes from the
// backend `project.capability` string via useCurrentProjectReadOnly.

export type ManagedRole = 'owner' | 'admin' | 'member' | string

export function normalizeManagedRole(role?: string | null): ManagedRole {
  const normalized = (role || '').toLowerCase()
  if (normalized === 'owner' || normalized === 'admin') return normalized
  // Legacy org roles (developer/viewer) and everything else fold into member.
  return 'member'
}

export function roleRank(role?: string | null): number {
  const normalized = normalizeManagedRole(role)
  if (normalized === 'owner') return 3
  if (normalized === 'admin') return 2
  return 1
}

export function canRead(role?: string | null): boolean {
  return roleRank(role) >= 1
}

export function canAdmin(role?: string | null): boolean {
  return roleRank(role) >= 2
}

export function canOwn(role?: string | null): boolean {
  return normalizeManagedRole(role) === 'owner'
}

export function roleLabel(t: Translator, role?: string | null): string {
  const normalized = normalizeManagedRole(role)
  if (normalized === 'owner') return t('manage.members.roleOwner')
  if (normalized === 'admin') return t('manage.members.roleAdmin')
  return t('manage.members.roleMember')
}

export function roleOptions(t: Translator, options?: { includeOwner?: boolean }) {
  const roles = [...(options?.includeOwner ? ['owner'] : []), 'admin', 'member']
  return roles.map((role) => ({ value: role, label: roleLabel(t, role) }))
}

// ── Per-project roles (admin/editor/viewer) — the capability vocabulary, ──
// also reused by API keys and skill collaborators.

export type ProjectRole = 'admin' | 'editor' | 'viewer'

export function projectRoleLabel(t: Translator, role?: string | null): string {
  switch ((role || '').toLowerCase()) {
    case 'admin':
      return t('manage.projectMembers.roleAdmin')
    case 'editor':
      return t('manage.projectMembers.roleEditor')
    case 'viewer':
      return t('manage.projectMembers.roleViewer')
    default:
      return role || '-'
  }
}

export function projectRoleOptions(t: Translator) {
  return (['admin', 'editor', 'viewer'] as const).map((role) => ({
    value: role,
    label: projectRoleLabel(t, role),
  }))
}

// ── Skill capability (owner/admin/editor/viewer/none) — the caller's effective ──
// tier on a skill, returned by the skill detail route. Managing collaborators is
// an admin-governance action, so only owner and admin qualify. The type is owned
// by types/managed.ts (single source); re-exported here for co-located ergonomics.

export type { SkillCapability } from '@/types/managed'

export function canManageSkillCollaborators(capability?: string | null): boolean {
  return capability === 'owner' || capability === 'admin'
}
