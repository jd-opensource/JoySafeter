'use client'

/**
 * Workspace Permissions Provider
 *
 * 🚧 功能状态: 待集成
 *
 * 用途: 管理 workspace 的权限系统
 *
 * 功能说明:
 * - 获取和管理 workspace 权限
 * - 计算用户权限（读/写/管理员等）
 * - 支持离线模式
 * - 集成协作工作流
 *
 * 提供的权限:
 * - canRead: 是否可以查看
 * - canEdit: 是否可以编辑
 * - canDelete: 是否可以删除
 * - canManageMembers: 是否可以管理成员
 * - isOfflineMode: 离线模式标记
 *
 * 当前状态:
 * - 代码完整，功能可用
 * - 暂未集成到应用布局中
 * - 依赖多个 hooks 和 stores
 *
 * 集成方式:
 * ```tsx
 * import { WorkspacePermissionsProvider } from './providers/workspace-permissions-provider'
 *
 * export default function Layout({ children }) {
 *   return (
 *     <WorkspacePermissionsProvider>
 *       {children}
 *     </WorkspacePermissionsProvider>
 *   )
 * }
 * ```
 */

import { useParams } from 'next/navigation'
import type React from 'react'
import { createContext, useContext, useMemo, useState } from 'react'

import { useUserPermissions, type WorkspaceUserPermissions } from '@/hooks/use-user-permissions'
import {
  useWorkspacePermissions,
  type WorkspacePermissions,
} from '@/hooks/use-workspace-permissions'
import { createLogger } from '@/lib/logs/console/logger'

const logger = createLogger('WorkspacePermissionsProvider')

interface WorkspacePermissionsContextType {
  // Raw workspace permissions data
  workspacePermissions: WorkspacePermissions | null
  permissionsLoading: boolean
  permissionsError: string | null
  updatePermissions: (newPermissions: WorkspacePermissions) => void
  refetchPermissions: () => Promise<void>

  // Computed user permissions (connection-aware)
  userPermissions: WorkspaceUserPermissions & { isOfflineMode?: boolean }

  // Connection state management
  setOfflineMode: (isOffline: boolean) => void
}

const WorkspacePermissionsContext = createContext<WorkspacePermissionsContextType>({
  workspacePermissions: null,
  permissionsLoading: false,
  permissionsError: null,
  updatePermissions: () => {},
  refetchPermissions: async () => {},
  userPermissions: {
    canRead: false,
    canEdit: false,
    canAdmin: false,
    userPermissions: 'read',
    isLoading: false,
    error: null,
  },
  setOfflineMode: () => {},
})

interface WorkspacePermissionsProviderProps {
  children: React.ReactNode
}

/**
 * Provider that manages workspace permissions and user access
 * Also provides connection-aware permissions that enforce read-only mode when offline
 */
export function WorkspacePermissionsProvider({ children }: WorkspacePermissionsProviderProps) {
  const params = useParams()
  const workspaceId = params?.workspaceId as string

  // Manage offline mode state locally
  const [isOfflineMode, setIsOfflineMode] = useState(false)

  // Fetch workspace permissions and loading state
  const {
    permissions: workspacePermissions,
    loading: permissionsLoading,
    error: permissionsError,
    updatePermissions,
    refetch: refetchPermissions,
  } = useWorkspacePermissions(workspaceId)

  // Get base user permissions from workspace permissions
  const baseUserPermissions = useUserPermissions(
    workspacePermissions,
    permissionsLoading,
    permissionsError
  )

  // Note: Connection-based error detection removed - only rely on operation timeouts
  // The 5-second operation timeout system will handle all error cases

  // Create connection-aware permissions that override user permissions when offline
  const userPermissions = useMemo((): WorkspaceUserPermissions & { isOfflineMode?: boolean } => {
    if (isOfflineMode) {
      // In offline mode, force read-only permissions regardless of actual user permissions
      return {
        ...baseUserPermissions,
        canEdit: false,
        canAdmin: false,
        // Keep canRead true so users can still view content
        canRead: baseUserPermissions.canRead,
        isOfflineMode: true,
      }
    }

    // When online, use normal permissions
    return {
      ...baseUserPermissions,
      isOfflineMode: false,
    }
  }, [baseUserPermissions, isOfflineMode])

  const contextValue = useMemo(
    () => ({
      workspacePermissions,
      permissionsLoading,
      permissionsError,
      updatePermissions,
      refetchPermissions,
      userPermissions,
      setOfflineMode: setIsOfflineMode,
    }),
    [
      workspacePermissions,
      permissionsLoading,
      permissionsError,
      updatePermissions,
      refetchPermissions,
      userPermissions,
    ]
  )

  return (
    <WorkspacePermissionsContext.Provider value={contextValue}>
      {children}
    </WorkspacePermissionsContext.Provider>
  )
}

/**
 * Hook to access workspace permissions and data from context
 * This provides both raw workspace permissions and computed user permissions
 */
export function useWorkspacePermissionsContext(): WorkspacePermissionsContextType {
  const context = useContext(WorkspacePermissionsContext)
  if (!context) {
    throw new Error(
      'useWorkspacePermissionsContext must be used within a WorkspacePermissionsProvider'
    )
  }
  return context
}

/**
 * Hook to access user permissions from context
 * This replaces individual useUserPermissions calls and includes connection-aware permissions
 */
export function useUserPermissionsContext(): WorkspaceUserPermissions & {
  isOfflineMode?: boolean
} {
  const { userPermissions } = useWorkspacePermissionsContext()
  return userPermissions
}
