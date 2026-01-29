'use client'

import { usePathname } from 'next/navigation'
import { useEffect } from 'react'

import { AppSidebar } from '@/components/app-sidebar'
import { InvitationNotification } from '@/components/invitation-notification/invitation-notification'
import { isPublicRoute } from '@/lib/core/constants/routes'
import { cn } from '@/lib/core/utils/cn'
import { useSidebarStore } from '@/stores/sidebar/store'

/**
 * AppShell Component - Global application layout
 *
 * Layout strategy:
 * 1. Authentication pages (/signin, /signup, etc.)
 *    - Do not display any sidebar
 *
 * 2. All application pages (/workspace, /chat, /memory, /discover)
 *    - Display AppSidebar (global navigation) on the far left
 *    - If the page has a Workspace Sidebar, it will be displayed side by side to the right of AppSidebar
 *    - Both sidebars can be managed and interacted with independently
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const setIsAppSidebarCollapsed = useSidebarStore((state) => state.setIsAppSidebarCollapsed)

  // Automatically determine whether to collapse based on pathname: collapse when path starts with /workspace
  const isAppSidebarCollapsed = pathname?.startsWith('/workspace') ?? false

  useEffect(() => {
    // Sync state to store so other components can access it
    setIsAppSidebarCollapsed(isAppSidebarCollapsed)
  }, [isAppSidebarCollapsed, setIsAppSidebarCollapsed])

  if (isPublicRoute(pathname)) {
    return <>{children}</>
  }
  return (
    <div className="flex h-screen bg-[var(--bg)]">
      <div
        className={cn(
          'transition-all duration-300 ease-in-out overflow-hidden flex-shrink-0',
          isAppSidebarCollapsed ? 'w-[64px]' : 'w-[140px]'
        )}
      >
        <AppSidebar isCollapsed={isAppSidebarCollapsed} />
      </div>
      <main className="flex-1 overflow-auto">
        {children}
      </main>
      <InvitationNotification />
    </div>
  )
}
