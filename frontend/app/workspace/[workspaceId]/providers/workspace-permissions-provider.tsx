/**
 * Re-export from the shared providers location.
 * This file is kept for backward compatibility with the workspace route tree.
 * New code should import from '@/providers/workspace-permissions-provider'.
 */
export {
  WorkspacePermissionsProvider,
  useWorkspacePermissionsContext,
  useUserPermissionsContext,
} from '@/providers/workspace-permissions-provider'
