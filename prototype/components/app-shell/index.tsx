'use client'

import { AnimatePresence, motion } from 'framer-motion'
import { usePathname } from 'next/navigation'

import { InvitationNotification } from '@/components/invitation-notification/invitation-notification'
import { TopNav } from '@/components/top-nav/top-nav'
import { isPublicRoute } from '@/lib/core/constants/routes'

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()

  // Canvas-heavy pages: hide topnav so the canvas fills the entire viewport
  const isCanvasPage =
    pathname?.startsWith('/build/workspace') ||
    pathname?.startsWith('/workspace') ||
    pathname?.startsWith('/openclaw')

  if (isPublicRoute(pathname)) {
    return <>{children}</>
  }

  if (isCanvasPage) {
    return (
      <div className="flex h-screen flex-col">
        <TopNav />
        <main className="flex-1 overflow-hidden">
          {children}
        </main>
        <InvitationNotification />
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col">
      <TopNav />

      <main className="flex-1">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={pathname}
            initial={{ opacity: 0, y: 10, filter: 'blur(4px)' }}
            animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            exit={{ opacity: 0, y: -6, filter: 'blur(2px)' }}
            transition={{ duration: 0.22, ease: [0.32, 0.72, 0, 1] }}
          >
            {children}
          </motion.div>
        </AnimatePresence>
      </main>

      <InvitationNotification />
    </div>
  )
}
