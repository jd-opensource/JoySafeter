'use client'

import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Building2, Info } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { ReactNode } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { managedGet } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { normalizeManagedRole } from '@/lib/managed/roles'
import { cn } from '@/lib/utils'
import { useProjectStore } from '@/stores/managed/project-store'
import type { OrganizationId } from '@/types/entity-id'

export interface OrganizationDetail {
  id: string
  name: string
  slug: string
  logo?: string | null
  role: string
  owner_name?: string | null
  owner_email?: string | null
  project_creation_policy: 'admins_only' | 'all_members'
  created_at?: string | null
}

const tabs = [
  { segment: '', labelKey: 'manage.organization.detail.tabs.overview' },
  { segment: 'members', labelKey: 'manage.organization.detail.tabs.members' },
]

export function OrganizationDetailShell({
  organizationId,
  children,
}: {
  organizationId: OrganizationId
  children: ReactNode
}) {
  const pathname = usePathname()
  const { t } = useTranslation()
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const organizationQuery = useQuery({
    queryKey: ['organization-detail', organizationId],
    queryFn: () => managedGet<OrganizationDetail>(`organizations/${organizationId}`),
    enabled: Boolean(organizationId),
  })
  const organization = organizationQuery.data

  if (organizationQuery.isLoading) {
    return (
      <div
        className="flex w-full flex-col gap-5"
        aria-label={t('manage.organization.detail.loading')}
      >
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-10 w-80 max-w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    )
  }

  if (!organization) {
    return (
      <div className="flex min-h-[240px] flex-col items-center justify-center gap-2 text-center">
        <h2 className="text-lg font-semibold text-foreground">
          {t('manage.organization.detail.notFoundTitle')}
        </h2>
        <p className="text-sm text-muted-foreground">
          {t('manage.organization.detail.notFoundDescription')}
        </p>
        <Link href="/managed/settings" className="text-sm text-primary hover:underline">
          {t('manage.organization.detail.backToOrganizations')}
        </Link>
      </div>
    )
  }

  const basePath = `/managed/settings/organizations/${organizationId}`
  const normalizedRole = normalizeManagedRole(organization.role)
  const isCurrent = currentOrgId === organization.id
  const isReadOnly = normalizedRole === 'member'

  return (
    <div className="flex w-full flex-col gap-6">
      <header className="flex flex-col gap-3">
        <Link
          href="/managed/settings"
          className="inline-flex w-fit items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          {t('manage.organization.detail.backToOrganizations')}
        </Link>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted">
              <Building2 className="size-5 text-muted-foreground" />
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm text-muted-foreground">{organization.slug}</p>
              <h1 className="truncate text-2xl font-semibold text-foreground">
                {organization.name}
              </h1>
              <p className="mt-1 truncate text-xs text-muted-foreground">
                {normalizedRole === 'owner'
                  ? t('sidebar.ownedByYou')
                  : `${t('manage.organization.ownedBy')} ${organization.owner_name || organization.owner_email || t('manage.organization.ownerUnknown')}`}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">
              {t(`manage.organization.detail.role.${normalizedRole}`)}
            </Badge>
            {isCurrent ? <Badge variant="outline">{t('manage.organization.current')}</Badge> : null}
          </div>
        </div>
      </header>

      {isReadOnly ? (
        <Alert>
          <Info />
          <AlertDescription>{t('manage.organization.detail.readOnly')}</AlertDescription>
        </Alert>
      ) : null}

      <nav
        aria-label={t('manage.organization.detail.tabs.label')}
        className="border-b border-border"
      >
        <div className="flex gap-6 overflow-x-auto">
          {tabs.map((tab) => {
            const href = tab.segment ? `${basePath}/${tab.segment}` : basePath
            const active = pathname === href
            return (
              <Link
                key={tab.segment || 'overview'}
                href={href}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'relative whitespace-nowrap px-0.5 pb-3 text-sm font-medium transition-colors',
                  active ? 'text-foreground' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {t(tab.labelKey)}
                {active ? (
                  <span className="absolute inset-x-0 -bottom-px h-0.5 bg-primary" />
                ) : null}
              </Link>
            )
          })}
        </div>
      </nav>

      {children}
    </div>
  )
}
