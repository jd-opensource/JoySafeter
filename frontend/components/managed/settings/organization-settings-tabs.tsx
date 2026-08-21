'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

const tabs = [
  {
    href: '/managed/settings',
    labelKey: 'manage.organization.tabs.organizations',
  },
  {
    href: '/managed/settings/members',
    labelKey: 'manage.organization.tabs.membersRoles',
  },
]

export function OrganizationSettingsTabs() {
  const pathname = usePathname()
  const { t } = useTranslation()

  return (
    <nav aria-label={t('manage.organization.tabs.label')} className="border-b border-border">
      <div className="flex gap-6 overflow-x-auto">
        {tabs.map((tab) => {
          const active =
            tab.href === '/managed/settings'
              ? pathname === tab.href
              : pathname === tab.href || pathname.startsWith(`${tab.href}/`)
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'border-b-2 border-transparent px-1 pb-3 pt-1 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground',
                active && 'border-primary text-foreground',
              )}
            >
              {t(tab.labelKey)}
            </Link>
          )
        })}
      </div>
    </nav>
  )
}
