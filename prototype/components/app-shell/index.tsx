'use client'

import { AnimatePresence, motion } from 'framer-motion'
import { usePathname } from 'next/navigation'

import { AppSidebar } from '@/components/app-sidebar/app-sidebar'
import { InvitationNotification } from '@/components/invitation-notification/invitation-notification'
import { isPublicRoute } from '@/lib/core/constants/routes'

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()

  const isCanvasPage =
    pathname?.startsWith('/build/workspace') ||
    pathname?.startsWith('/workspace') ||
    pathname?.startsWith('/openclaw')

  if (isPublicRoute(pathname)) {
    return <>{children}</>
  }

  if (isCanvasPage) {
    return (
      <div className="flex h-screen executive-shell">
        <div className="w-[72px] flex-shrink-0">
          <AppSidebar isCollapsed />
        </div>
        <main className="flex-1 overflow-hidden bg-transparent">
          {children}
        </main>
        <InvitationNotification />
      </div>
    )
  }

  return (
    <div className="flex h-screen executive-shell">
      <div className="w-[var(--sidebar-width)] flex-shrink-0">
        <AppSidebar />
      </div>

      <main className="flex-1 overflow-y-auto bg-transparent">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={pathname}
            initial={{ opacity: 0, y: 10, filter: 'blur(3px)' }}
            animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            exit={{ opacity: 0, y: -6, filter: 'blur(2px)' }}
            transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
            className="min-h-full"
          >
            {children}
          </motion.div>
        </AnimatePresence>
      </main>

      <InvitationNotification />
    </div>
  )
}
