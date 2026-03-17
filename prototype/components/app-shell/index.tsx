'use client'

import { AnimatePresence, motion } from 'framer-motion'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'


import { AppSidebar, type MenuItem, menuItems } from '@/components/app-sidebar'
import { InvitationNotification } from '@/components/invitation-notification/invitation-notification'
import { isPublicRoute } from '@/lib/core/constants/routes'
import { cn } from '@/lib/core/utils/cn'
import { useSidebarStore } from '@/stores/sidebar/store'

function SecondarySidebar({ activeItem }: { activeItem: MenuItem }) {
  const pathname = usePathname()
  const { t } = useTranslation()

  return (
    <motion.div
      initial={{ width: 0, opacity: 0 }}
      animate={{ width: 200, opacity: 1 }}
      exit={{ width: 0, opacity: 0 }}
      transition={{ duration: 0.2, ease: [0.32, 0.72, 0, 1] }}
      className="h-screen flex-shrink-0 overflow-hidden border-r border-[var(--border)] bg-[var(--surface-1)]"
    >
      <div className="flex h-full w-[200px] flex-col">
        <div className="px-3 py-4">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            {t(activeItem.labelKey)}
          </h3>
        </div>
        <nav className="flex-1 px-2">
          <ul className="space-y-0.5">
            {activeItem.subItems!.map((sub) => {
              const isActive = pathname === sub.href
              return (
                <li key={sub.id}>
                  <Link
                    href={sub.href}
                    className={cn(
                      'flex items-center rounded-md px-3 py-1.5 text-[13px] transition-colors',
                      isActive
                        ? 'bg-[var(--surface-5)] font-medium text-[var(--text-primary)]'
                        : 'text-[var(--text-tertiary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]'
                    )}
                  >
                    {t(sub.labelKey)}
                  </Link>
                </li>
              )
            })}
          </ul>
        </nav>
      </div>
    </motion.div>
  )
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const setIsAppSidebarCollapsed = useSidebarStore((state) => state.setIsAppSidebarCollapsed)

  // Collapse sidebar for canvas-heavy pages
  const isAppSidebarCollapsed = !!(
    pathname?.startsWith('/build/workspace') ||
    pathname?.startsWith('/workspace') ||
    pathname?.startsWith('/openclaw')
  )

  useEffect(() => {
    setIsAppSidebarCollapsed(isAppSidebarCollapsed)
  }, [isAppSidebarCollapsed, setIsAppSidebarCollapsed])

  const activeMenuItem = useMemo<MenuItem | null>(() => {
    if (!pathname) return null
    return (
      menuItems.find((item) => {
        if (item.id === 'home') return pathname === '/'
        return item.matchPaths?.some((p) => pathname.startsWith(p)) ?? pathname.startsWith(item.href)
      }) ?? null
    )
  }, [pathname])

  // Only show secondary sidebar when primary is expanded AND item has sub-items
  const showSecondarySidebar =
    !isAppSidebarCollapsed &&
    activeMenuItem !== null &&
    (activeMenuItem.subItems?.length ?? 0) > 0

  if (isPublicRoute(pathname)) {
    return <>{children}</>
  }

  return (
    <div className="flex h-screen bg-[var(--bg)]">
      {/* Primary sidebar */}
      <div
        className={cn(
          'transition-all duration-300 ease-in-out overflow-hidden flex-shrink-0',
          isAppSidebarCollapsed ? 'w-[64px]' : 'w-[140px]'
        )}
      >
        <AppSidebar isCollapsed={isAppSidebarCollapsed} />
      </div>

      {/* Secondary sidebar — slides in when primary is expanded and item has sub-items */}
      <AnimatePresence initial={false}>
        {showSecondarySidebar && (
          <SecondarySidebar key={activeMenuItem!.id} activeItem={activeMenuItem!} />
        )}
      </AnimatePresence>

      {/* Main content with page transition */}
      <main className="flex-1 overflow-auto">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={pathname}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.18, ease: [0.32, 0.72, 0, 1] }}
            className="h-full"
          >
            {children}
          </motion.div>
        </AnimatePresence>
      </main>

      <InvitationNotification />
    </div>
  )
}
