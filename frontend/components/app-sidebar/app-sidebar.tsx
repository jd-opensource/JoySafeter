'use client'

import {
  LayoutDashboard,
  Blocks,
  ShieldCheck,
  Wrench,
  Brain,
  Clapperboard,
  Activity,
  Target,
  Bot,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { env as runtimeEnv } from 'next-runtime-env'

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { AppLogo } from './app-logo'
import { UserInfo } from './user-info'
import { VersionBadge } from './version-badge'

interface MenuItem {
  id: string
  labelKey: string
  icon: typeof LayoutDashboard
  href: string
}

interface MenuGroup {
  label?: string // optional small group label (hidden when collapsed)
  items: MenuItem[]
}

const menuGroups: MenuGroup[] = [
  {
    // WORK — daily workflows
    items: [
      { id: 'agents', labelKey: 'sidebar.agents', icon: Bot, href: '/agents' },
      { id: 'runs', labelKey: 'sidebar.runCenter', icon: Activity, href: '/runs' },
      { id: 'tasks', labelKey: 'sidebar.tasks', icon: Target, href: '/tasks' },
    ],
  },
  {
    // CONFIGURE — agents, skills, tools
    items: [
      { id: 'agent', labelKey: 'sidebar.agentBuilder', icon: Blocks, href: '/workspace' },
      { id: 'skills', labelKey: 'sidebar.skillsHub', icon: ShieldCheck, href: '/skills' },
      { id: 'tools', labelKey: 'sidebar.toolsAndMcp', icon: Wrench, href: '/tools' },
    ],
  },
  {
    // MONITOR — memory, openclaw
    items: [
      { id: 'memory', labelKey: 'sidebar.memory', icon: Brain, href: '/memory' },
      { id: 'openclaw', labelKey: 'sidebar.openclaw', icon: Clapperboard, href: '/openclaw' },
    ],
  },
]

interface AppSidebarProps {
  isCollapsed?: boolean
}

export function AppSidebar({ isCollapsed = false }: AppSidebarProps) {
  const pathname = usePathname()
  const { t } = useTranslation()

  // NEXT_PUBLIC_OPENCLAW_ENABLED controls OpenClaw visibility at deployment level
  // Defaults to hidden (false) when env var is not set; set to "true" to show
  const openclawEnv =
    runtimeEnv('NEXT_PUBLIC_OPENCLAW_ENABLED') || process.env.NEXT_PUBLIC_OPENCLAW_ENABLED
  const openclawEnabled = openclawEnv?.toLowerCase() === 'true' || openclawEnv === '1'

  // Filter out openclaw if disabled
  const visibleGroups = menuGroups.map((group) => ({
    ...group,
    items: openclawEnabled ? group.items : group.items.filter((item) => item.id !== 'openclaw'),
  }))

  return (
    <TooltipProvider>
      <aside className="flex h-screen w-full flex-shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-elevated)]">
        <div className="flex h-full flex-col">
          <AppLogo isCollapsed={isCollapsed} />

          <nav className="flex-1 px-2 py-2">
            {visibleGroups.map((group, groupIdx) => (
              <div key={groupIdx}>
                {groupIdx > 0 && <div className="mx-2 my-2 border-t border-[var(--border)]" />}
                <ul className="space-y-1">
                  {group.items.map((item) => {
                    const Icon = item.icon
                    const isActive = pathname?.startsWith(item.href)
                    const label = t(item.labelKey)

                    const menuItem = (
                      <Link
                        href={item.href}
                        className={cn(
                          'flex items-center gap-2 rounded-lg px-2 py-1.5 text-base leading-[16px] transition-colors',
                          isCollapsed ? 'justify-center' : '',
                          isActive
                            ? 'bg-[var(--surface-5)] font-medium text-[var(--text-primary)]'
                            : 'font-normal text-[var(--text-tertiary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]',
                        )}
                      >
                        <Icon
                          className="h-3.5 w-3.5 flex-shrink-0"
                          strokeWidth={isActive ? 2 : 1.75}
                        />
                        {!isCollapsed && <span className="truncate">{label}</span>}
                      </Link>
                    )

                    return (
                      <li key={item.id}>
                        {isCollapsed ? (
                          <Tooltip>
                            <TooltipTrigger asChild>{menuItem}</TooltipTrigger>
                            <TooltipContent side="right">{label}</TooltipContent>
                          </Tooltip>
                        ) : (
                          menuItem
                        )}
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
