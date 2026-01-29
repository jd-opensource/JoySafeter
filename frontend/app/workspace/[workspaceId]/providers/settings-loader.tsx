'use client'

/**
 * Settings Loader
 *
 * 🚧 功能状态: 待集成
 *
 * 用途: 在 workspace 会话启动时加载用户设置
 *
 * 功能说明:
 * - 使用 React Query 从数据库获取用户设置
 * - 自动同步到 Zustand store
 * - 确保设置在整个应用中可用
 *
 * 当前状态:
 * - 代码完整，功能可用
 * - 暂未集成到应用布局中
 * - 依赖 @/hooks/queries/general-settings
 *
 * 集成方式:
 * 在 workspace 布局中添加:
 * ```tsx
 * import { SettingsLoader } from './providers/settings-loader'
 *
 * export default function Layout({ children }) {
 *   return (
 *     <>
 *       <SettingsLoader />
 *       {children}
 *     </>
 *   )
 * }
 * ```
 */

import { useEffect, useRef } from 'react'

import { useGeneralSettings } from '@/hooks/queries/general-settings'
import { useSession } from '@/lib/auth/auth-client'

export function SettingsLoader() {
  const { data: session, isPending: isSessionPending } = useSession()
  const hasLoadedRef = useRef(false)

  // Use React Query hook which automatically syncs to Zustand
  // This replaces the old Zustand loadSettings() call
  const { refetch } = useGeneralSettings()

  useEffect(() => {
    // Only load settings once per session for authenticated users
    if (!isSessionPending && session?.user && !hasLoadedRef.current) {
      hasLoadedRef.current = true
      // Force refetch from DB on initial workspace entry
      refetch()
    }
  }, [isSessionPending, session?.user, refetch])

  return null
}
