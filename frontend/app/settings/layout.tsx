'use client'

import { Cpu, Users, Box, Key } from 'lucide-react'
import Link from 'next/link'
import { usePathname, useParams } from 'next/navigation'

import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { useCurrentWorkspace } from '@/providers/workspace-provider'

/**
 * Global settings layout (e.g. /settings/models)
 */
export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation()
  const pathname = usePathname()
  const params = useParams()
  const { workspaceId: currentWorkspaceId } = useCurrentWorkspace()
  const workspaceId = (params?.workspaceId as string) || currentWorkspaceId

  const navItems = [
    {
      id: 'members',
      label: t('settings.membersManagementTitle'),
      icon: Users,
      href: workspaceId ? `/settings/members/${workspaceId}` : '/settings/members',
    },
    {
      id: 'models',
      label: t('settings.models'),
      icon: Cpu,
      href: '/settings/models',
    },
    {
      id: 'sandboxes',
      label: t('settings.sandboxes.title'),
      icon: Box,
      href: '/settings/sandboxes',
    },
    {
      id: 'tokens',
      label: t('settings.tokens.title'),
      icon: Key,
      href: '/settings/tokens',
    },
  ]

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--bg)]">
      {/* Settings Internal Sidebar */}
      <aside className="w-64 flex-shrink-0 border-r border-[var(--border)] bg-[var(--surface-elevated)]">
        <div className="flex h-full flex-col">
          <div className="flex h-14 items-center border-b border-[var(--border)] px-6">
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">
              {t('settings.workspace')}
            </h2>
          </div>

          <nav className="flex-1 space-y-1 px-3 py-4">
            {navItems.map((item) => {
              const Icon = item.icon
              const isActive = pathname?.startsWith(item.href)

              return (
                <Link
                  key={item.id}
                  href={item.href}
                  className={cn(
                    'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all duration-200',
                    isActive
                      ? 'bg-[var(--surface-5)] font-medium text-[var(--text-primary)] shadow-sm'
                      : 'text-[var(--text-tertiary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]',
                  )}
                >
                  <Icon
                    size={18}
                    className={cn(isActive ? 'text-[var(--brand-600)]' : 'text-[var(--text-muted)]')}
                  />
                  {item.label}
                </Link>
              )
            })}
          </nav>
        </div>
      </aside>

      {/* Settings Content Area */}
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">{children}</main>
    </div>
  )
}
