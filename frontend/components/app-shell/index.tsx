'use client'

import { usePathname } from 'next/navigation'

import { AppSidebar } from '@/components/app-sidebar'
import { isPublicRoute } from '@/lib/core/constants/routes'
import { useSidebarStore } from '@/stores/sidebar/store'

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const isCollapsed = useSidebarStore((state) => state.isCollapsed)

  if (isPublicRoute(pathname)) {
    return <>{children}</>
  }
  return (
    <div className="h-screen overflow-hidden bg-background">
      <AppSidebar />
      <main
        className={`${isCollapsed ? 'ml-[52px]' : 'ml-[220px]'} relative z-0 h-screen overflow-auto p-8 transition-[margin] duration-200`}
      >
        {children}
      </main>
    </div>
  )
}
