'use client'

import { usePathname } from 'next/navigation'
import { useEffect } from 'react'

import { AppSidebar } from '@/components/app-sidebar'
import { isPublicRoute } from '@/lib/core/constants/routes'
import { useSidebarStore } from '@/stores/sidebar/store'

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const setIsAppSidebarCollapsed = useSidebarStore((state) => state.setIsAppSidebarCollapsed)

  useEffect(() => {
    setIsAppSidebarCollapsed(false)
  }, [setIsAppSidebarCollapsed])

  if (isPublicRoute(pathname)) {
    return <>{children}</>
  }
  return (
    <div className="flex h-screen bg-[var(--bg)]">
      <div
        style={{ width: 'var(--sidebar-width)' }}
        className="flex-shrink-0 overflow-hidden transition-all duration-300 ease-in-out"
      >
        <AppSidebar />
      </div>
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  )
}
