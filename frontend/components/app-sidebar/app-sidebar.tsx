'use client'

import { useQuery } from '@tanstack/react-query'
import {
  LayoutDashboard,
  Blocks,
  Compass,
  ShieldCheck,
  Wrench,
  Brain,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useTranslation } from 'react-i18next'

import { NotificationCenter } from '@/components/notification-center/notification-center'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/core/utils/cn'
import { workspaceService } from '@/services/workspaceService'

import { AppLogo } from './app-logo'
import { UserInfo } from './user-info'


const menuItems = [
  {
    id: 'dashboard',
    labelKey: 'sidebar.dashboard',
    icon: LayoutDashboard,
    href: '/chat',
  },
  {
    id: 'agent',
    labelKey: 'sidebar.agentBuilder',
    icon: Blocks,
    href: '/workspace',
  },
  // {
  //   id: 'discover',
  //   labelKey: 'sidebar.discover',
  //   icon: Compass,
  //   href: '/discover',
  // },
  {
    id: 'tools',
    labelKey: 'sidebar.toolsAndMcp',
    icon: Wrench,
    href: '/tools',
  },
  {
    id: 'skills',
    labelKey: 'sidebar.skillsHub',
    icon: ShieldCheck,
    href: '/skills',
  },
  {
    id: 'memory',
    labelKey: 'sidebar.memory',
    icon: Brain,
    href: '/memory',
  },
]

interface AppSidebarProps {
  isCollapsed?: boolean
}

export function AppSidebar({ isCollapsed = false }: AppSidebarProps) {
  const pathname = usePathname()
  const { t } = useTranslation()

  const { data: pendingData } = useQuery<{ invitations: any[] }>({
    queryKey: ['workspace-invitations', 'pending'],
    queryFn: () => workspaceService.getPendingInvitations(),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })

  const pendingCount = pendingData?.invitations?.length || 0

  return (
    <TooltipProvider>
      <aside className="flex h-screen w-full flex-shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-elevated)]">
        <div className="flex h-full flex-col">
          <AppLogo isCollapsed={isCollapsed} />

          <nav className="flex-1 py-2 px-2">
            <ul className="space-y-1">
              {menuItems.map((item) => {
                const Icon = item.icon
                const isActive = pathname?.startsWith(item.href)
                const label = t(item.labelKey)

                const menuItem = (
                  <Link
                    href={item.href}
                    className={cn(
                      'flex items-center gap-2 rounded-lg px-2 py-2 text-[13px] font-medium transition-colors',
                      isCollapsed ? 'justify-center' : '',
                      isActive
                        ? 'bg-[var(--surface-5)] text-[var(--text-primary)]'
                        : 'text-[var(--text-secondary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]'
                    )}
                  >
                    <Icon className="h-[16px] w-[16px] flex-shrink-0" />
                    {!isCollapsed && <span className="truncate">{label}</span>}
                  </Link>
                )

                return (
                  <li key={item.id}>
                    {isCollapsed ? (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          {menuItem}
                        </TooltipTrigger>
                        <TooltipContent side="right">
                          {label}
                        </TooltipContent>
                      </Tooltip>
                    ) : (
                      menuItem
                    )}
                  </li>
                )
              })}
            </ul>
          </nav>

          <div className="px-2 pb-2">
            {!isCollapsed && pendingCount > 0 && (
              <div className="mb-2 px-3 py-1.5 rounded-md bg-blue-50 dark:bg-blue-950/20">
                <div className="flex items-center gap-2">
                  <div className="flex-shrink-0">
                    <div className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
                  </div>
                  <span className="text-[10px] font-medium text-blue-700 dark:text-blue-300 truncate">
                    {pendingCount} {pendingCount === 1 ? t('notifications.pendingItem') : t('notifications.pendingItems')}
                  </span>
                </div>
              </div>
            )}

              {isCollapsed ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                  <NotificationCenter>
                    <button
                      className={cn(
                        'flex items-center justify-center rounded-lg px-2 py-2 text-[13px] font-medium transition-colors w-full relative',
                        pendingCount > 0
                          ? 'text-blue-700 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900/20'
                          : 'text-[var(--text-secondary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]'
                      )}
                    >
                      <div className="relative">
                        <svg
                          className={cn(
                            "h-[16px] w-[16px] flex-shrink-0",
                            pendingCount > 0 && "text-blue-600 dark:text-blue-400"
                          )}
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
                          />
                        </svg>
                        {pendingCount > 0 && (
                          <span className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[9px] font-bold text-white shadow-md ring-2 ring-white dark:ring-gray-800">
                            {pendingCount > 9 ? '9+' : pendingCount}
                          </span>
                        )}
                      </div>
                    </button>
                  </NotificationCenter>
                  </TooltipTrigger>
                  <TooltipContent side="right">
                    {t('sidebar.notifications')}
                  </TooltipContent>
                </Tooltip>
              ) : (
              <NotificationCenter>
                <button
                  className={cn(
                    'flex items-center gap-2 rounded-lg px-2 py-2 text-[13px] font-medium transition-colors w-full relative',
                    pendingCount > 0
                      ? 'text-blue-700 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900/20'
                      : 'text-[var(--text-secondary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]'
                  )}
                >
                  <div className="relative">
                    <svg
                      className={cn(
                        "h-[16px] w-[16px] flex-shrink-0",
                        pendingCount > 0 && "text-blue-600 dark:text-blue-400"
                      )}
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
                      />
                    </svg>
                    {pendingCount > 0 && (
                      <span className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[9px] font-bold text-white shadow-md ring-2 ring-white dark:ring-gray-800">
                        {pendingCount > 9 ? '9+' : pendingCount}
                      </span>
                    )}
                  </div>
                  <span className="flex-1 text-left truncate">{t('sidebar.notifications')}</span>
                </button>
              </NotificationCenter>
              )}
          </div>

          <UserInfo isCollapsed={isCollapsed} showContent={!isCollapsed} />
        </div>
      </aside>
    </TooltipProvider>
  )
}
