'use client'

import {
  Bot,
  LayoutDashboard,
  ListChecks,
  Sparkles,
  Wrench,
  Settings,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useSidebarStore } from '@/stores/sidebar/store'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { AppLogo } from './app-logo'
import { UserInfo } from './user-info'
import { VersionBadge } from './version-badge'

interface MenuItem {
  id: string
  labelKey: string
  icon: typeof Bot
  href: string
}

interface MenuGroup {
  items: MenuItem[]
}

const menuGroups: MenuGroup[] = [
  {
    items: [
      { id: 'dashboard', labelKey: 'sidebar.dashboard', icon: LayoutDashboard, href: '/dashboard' },
    ],
  },
  {
    items: [
      { id: 'agents', labelKey: 'sidebar.agents', icon: Bot, href: '/agents' },
      { id: 'tasks', labelKey: 'sidebar.tasks', icon: ListChecks, href: '/tasks' },
    ],
  },
  {
    items: [
      { id: 'skills', labelKey: 'sidebar.skillsHub', icon: Sparkles, href: '/skills' },
      { id: 'tools', labelKey: 'sidebar.toolsAndMcp', icon: Wrench, href: '/tools' },
    ],
  },
  {
    items: [
      { id: 'settings', labelKey: 'sidebar.settings', icon: Settings, href: '/settings' },
    ],
  },
]

export function AppSidebar() {
  const pathname = usePathname()
  const { t } = useTranslation()
  const isCollapsed = useSidebarStore((state) => state.isCollapsed)

  return (
    <TooltipProvider>
      <aside className="flex h-screen w-full flex-shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-elevated)]">
        <div className="flex h-full flex-col">
          <AppLogo isCollapsed={isCollapsed} />

          <nav className="flex-1 px-2 py-2">
            {menuGroups.map((group, groupIdx) => (
              <div key={groupIdx}>
                {groupIdx > 0 && <div className="mx-2 my-2 border-t border-[var(--border)]" />}
                <ul className="space-y-1">
                  {group.items.map((item) => {
                    const Icon = item.icon
                    const isActive = pathname?.startsWith(item.href)
                    const label = t(item.labelKey)

                    return (
                      <li key={item.id}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Link
                              href={item.href}
                              className={cn(
                                'flex items-center rounded-lg px-3 py-2 text-sm transition-colors',
                                isCollapsed ? 'justify-center' : 'gap-2.5',
                                isActive
                                  ? 'bg-[var(--surface-5)] font-medium text-[var(--text-primary)]'
                                  : 'font-normal text-[var(--text-tertiary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]',
                              )}
                            >
                              <Icon
                                className="h-4 w-4 flex-shrink-0"
                                strokeWidth={isActive ? 2 : 1.75}
                              />
                              {!isCollapsed && <span className="truncate">{label}</span>}
                            </Link>
                          </TooltipTrigger>
                          <TooltipContent side="right" className={cn(!isCollapsed && "hidden")}>{label}</TooltipContent>
                        </Tooltip>
                      </li>
                    )
                  })}
                </ul>
              </div>
            ))}
          </nav>

          <UserInfo isCollapsed={isCollapsed} showContent={!isCollapsed} />
          <VersionBadge isCollapsed={isCollapsed} />
        </div>
      </aside>
    </TooltipProvider>
  )
}
