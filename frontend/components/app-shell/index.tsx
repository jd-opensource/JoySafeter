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
        className={`ml-[52px] ${isCollapsed ? 'sm:ml-[52px]' : 'sm:ml-[220px]'} relative z-0 h-screen overflow-auto p-3 transition-[margin] duration-200 sm:p-5`}
      >
        {children}
      </main>
    </div>
  )
}
