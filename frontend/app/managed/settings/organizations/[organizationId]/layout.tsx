import type { ReactNode } from 'react'

import { OrganizationDetailShell } from '@/components/managed/settings/organization-detail-shell'

export default async function OrganizationDetailLayout({
  children,
  params,
}: {
  children: ReactNode
  params: Promise<{ organizationId: string }>
}) {
  const { organizationId } = await params
  return (
    <OrganizationDetailShell organizationId={organizationId}>{children}</OrganizationDetailShell>
  )
}
