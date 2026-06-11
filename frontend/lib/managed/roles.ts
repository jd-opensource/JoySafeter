type Translator = (key: string) => string

export type ManagedRole = 'owner' | 'admin' | 'developer' | 'member' | 'viewer' | string

export function normalizeManagedRole(role?: string | null): ManagedRole {
  if (!role) return 'viewer'
  return role.toLowerCase() === 'member' ? 'developer' : role.toLowerCase()
}

export function roleRank(role?: string | null): number {
  const normalized = normalizeManagedRole(role)
  if (normalized === 'owner') return 4
  if (normalized === 'admin') return 3
  if (normalized === 'developer') return 2
  if (normalized === 'viewer') return 1
  return 0
}

export function canRead(role?: string | null): boolean {
  return roleRank(role) >= 1
}

export function canWrite(role?: string | null): boolean {
  return roleRank(role) >= 2
}

export function canAdmin(role?: string | null): boolean {
  return roleRank(role) >= 3
}

export function canOwn(role?: string | null): boolean {
  return normalizeManagedRole(role) === 'owner'
}

export function roleLabel(t: Translator, role?: string | null): string {
  const normalized = normalizeManagedRole(role)
  if (normalized === 'owner') return t('manage.members.roleOwner')
  if (normalized === 'admin') return t('manage.members.roleAdmin')
  if (normalized === 'developer') return t('manage.members.roleDeveloper')
  if (normalized === 'viewer') return t('manage.members.roleViewer')
  return role || '-'
}

export function roleOptions(t: Translator, options?: { includeOwner?: boolean; includeMemberAlias?: boolean }) {
  const roles = [
    ...(options?.includeOwner ? ['owner'] : []),
    'admin',
    options?.includeMemberAlias ? 'member' : 'developer',
    'viewer',
  ]

  return roles.map((role) => ({ value: role, label: roleLabel(t, role) }))
}
