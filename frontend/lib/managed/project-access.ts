export type ProjectAccessState = 'org_wide' | 'default' | 'explicit' | 'none'
export type ProjectPermission = 'admin' | 'editor' | 'viewer'

const PROJECT_PERMISSIONS = new Set<ProjectPermission>(['admin', 'editor', 'viewer'])

export function effectiveProjectAccessValue(
  access?: string | null,
  projectRole?: string | null,
): ProjectAccessState | ProjectPermission {
  if (access === 'org_wide') return 'org_wide'
  if (access === 'default') return 'viewer'
  if (access !== 'explicit') return 'none'

  const normalized = (projectRole || '').trim().toLowerCase() as ProjectPermission
  return PROJECT_PERMISSIONS.has(normalized) ? normalized : 'viewer'
}

export function canManageProjectAccess(capability?: string | null): boolean {
  return capability === 'admin'
}
