'use client'

import { useSidebarStore } from '@/stores/sidebar/store'

import { Sidebar } from './components/sidebar/sidebar'
import { GlobalCommandsProvider } from './providers/global-commands-provider'

/**
 * Workspace Detail Layout
 *
 * Provides workspace-level functionality:
 * - GlobalCommandsProvider: workspace global commands (keyboard shortcuts)
 * - Sidebar: workspace navigation and agent management
 *
 * Layout structure:
 * - AppSidebar (fixed 140px) is rendered in AppShell
 * - Workspace Sidebar is fixed at left-[140px] position (adjustable width)
 * - Main content area occupies remaining space, left margin adapts to Workspace Sidebar state
 *
 * Note:
 * - SocketProvider and Tooltip.Provider are provided in parent layout
 * - AppSidebar (global navigation) is rendered in root layout's AppShell, fixed width
 * - Workspace Sidebar uses fixed positioning, fixed to the right of AppSidebar
 */
export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const workspaceSidebarWidth = useSidebarStore((state) => state.sidebarWidth)
  const isWorkspaceSidebarCollapsed = useSidebarStore((state) => state.isCollapsed)
  const isAppSidebarCollapsed = useSidebarStore((state) => state.isAppSidebarCollapsed)

  // Calculate workspace sidebar width for content margin
  // Only account for workspace sidebar, not AppSidebar (handled by AppShell)
  const contentMarginLeft = isWorkspaceSidebarCollapsed ? 0 : workspaceSidebarWidth

  return (
    <GlobalCommandsProvider>
      <Sidebar />
      <div
        className='flex-1 h-full overflow-hidden transition-all duration-300'
        style={{ marginLeft: `${contentMarginLeft}px` }}
      >
        {children}
      </div>
    </GlobalCommandsProvider>
  )
}
