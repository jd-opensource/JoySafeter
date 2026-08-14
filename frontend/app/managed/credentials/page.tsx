'use client'

import { CredentialManagementShell } from '@/components/managed/credentials/credential-management-shell'
import { PageHeader } from '@/components/managed/shared'
import { useTranslation } from '@/lib/i18n'

export default function CredentialsPage() {
  const { t } = useTranslation()
  return (
    <div>
      <PageHeader title={t('managed.credentials.title')} subtitle={t('managed.credentials.subtitle')} />
      <CredentialManagementShell />
    </div>
  )
}
