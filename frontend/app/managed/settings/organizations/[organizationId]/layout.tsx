import type { ReactNode } from 'react'

import { OrganizationDetailShell } from '@/components/managed/settings/organization-detail-shell'
import { parseOrganizationId } from '@/types/entity-id'

export default async function OrganizationDetailLayout({
  children,
  params,
}: {
  children: ReactNode
  params: Promise<{ organizationId: string }>
}) {
  const { organizationId } = await params
  return (
    <OrganizationDetailShell organizationId={parseOrganizationId(organizationId)}>
      {children}
    </OrganizationDetailShell>
  )
}
