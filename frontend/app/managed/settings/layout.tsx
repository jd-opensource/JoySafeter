import type { ReactNode } from 'react'

import { OrganizationSettingsTabs } from '@/components/managed/settings/organization-settings-tabs'

export default function OrganizationSettingsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex w-full flex-col gap-6">
      <OrganizationSettingsTabs />
      {children}
    </div>
  )
}
