'use client'

import { Building2, Info } from 'lucide-react'
import Link from 'next/link'
import type { ReactNode } from 'react'

import { PageHeader, TabNav } from '@/components/managed/shared'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useManagedOrganization } from '@/hooks/managed/use-managed-organization'
import { useTranslation } from '@/lib/i18n'
import { normalizeManagedRole } from '@/lib/managed/roles'
import { useProjectStore } from '@/stores/managed/project-store'
import type { OrganizationId } from '@/types/entity-id'

export type { OrganizationDetail } from '@/lib/managed/tenant-response-parsers'

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
  const { t } = useTranslation()
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const organizationQuery = useManagedOrganization(organizationId)
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
    <div>
      <PageHeader
        title={organization.name}
        icon={<Building2 />}
        breadcrumb={[
          { label: t('manage.organization.title'), to: '/managed/settings' },
          { label: organization.name },
        ]}
        titleExtra={
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">
              {t(`manage.organization.detail.role.${normalizedRole}`)}
            </Badge>
            {isCurrent ? <Badge variant="outline">{t('manage.organization.current')}</Badge> : null}
          </div>
        }
        subtitle={
          <>
            <span className="block truncate">{organization.slug}</span>
            <span className="block truncate">
              {normalizedRole === 'owner'
                ? t('sidebar.ownedByYou')
                : `${t('manage.organization.ownedBy')} ${organization.owner_name || organization.owner_email || t('manage.organization.ownerUnknown')}`}
            </span>
          </>
        }
      />

      {isReadOnly ? (
        <Alert className="mb-6">
          <Info />
          <AlertDescription>{t('manage.organization.detail.readOnly')}</AlertDescription>
        </Alert>
      ) : null}

      <TabNav
        label={t('manage.organization.detail.tabs.label')}
        items={tabs.map((tab) => ({
          href: tab.segment ? `${basePath}/${tab.segment}` : basePath,
          label: t(tab.labelKey),
        }))}
      />

      {children}
    </div>
  )
}
