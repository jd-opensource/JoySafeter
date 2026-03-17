/**
 * Workspace permission type definitions
 *
 * Maps backend WorkspaceMemberRole (owner/admin/member/viewer)
 * to frontend permission types (read/write/admin)
 */

/**
 * Backend workspace member role
 */
export type WorkspaceMemberRole = 'owner' | 'admin' | 'member' | 'viewer'

/**
 * Frontend permission type (compatible with reference project's permission system)
 */
export type PermissionType = 'read' | 'write' | 'admin'

/**
 * Maps backend role to frontend permission type
 */
export function mapRoleToPermissionType(role: WorkspaceMemberRole): PermissionType {
  switch (role) {
    case 'owner':
    case 'admin':
      return 'admin'
    case 'member':
      return 'write'
    case 'viewer':
      return 'read'
    default:
      return 'read'
  }
}

/**
 * Permission type enum values (for type inference)
 */
export const permissionTypeEnum = {
  enumValues: ['read', 'write', 'admin'] as const,
} as const
