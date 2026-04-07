'use client'

import {
  LayoutDashboard,
  Blocks,
  ShieldCheck,
  Wrench,
  Brain,
  Clapperboard,
  Activity,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { env as runtimeEnv } from 'next-runtime-env'

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

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
    id: 'runs',
    labelKey: 'sidebar.runCenter',
    icon: Activity,
    href: '/runs',
  },
  {
    id: 'memory',
    labelKey: 'sidebar.memory',
    icon: Brain,
    href: '/memory',
  },
  {
    id: 'openclaw',
    labelKey: 'sidebar.openclaw',
    icon: Clapperboard,
    href: '/openclaw',
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

  const visibleMenuItems = openclawEnabled
    ? menuItems
    : menuItems.filter((item) => item.id !== 'openclaw')

  return (
    <TooltipProvider>
      <aside className="flex h-screen w-full flex-shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-elevated)]">
        <div className="flex h-full flex-col">
          <AppLogo isCollapsed={isCollapsed} />

          <nav className="flex-1 px-2 py-2">
            <ul className="space-y-1">
              {visibleMenuItems.map((item) => {
                const Icon = item.icon
                const isActive = pathname?.startsWith(item.href)
                const label = t(item.labelKey)

                const menuItem = (
                  <Link
                    href={item.href}
                    className={cn(
                      'flex items-center gap-2 rounded-lg px-2 py-2 text-small font-medium transition-colors',
                      isCollapsed ? 'justify-center' : '',
                      isActive
                        ? 'bg-[var(--surface-5)] text-[var(--text-primary)]'
                        : 'text-[var(--text-secondary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]',
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
          </nav>

          <UserInfo isCollapsed={isCollapsed} showContent={!isCollapsed} />
        </div>
      </aside>
    </TooltipProvider>
  )
}
