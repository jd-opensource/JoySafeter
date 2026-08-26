'use client'

import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { ResourceErrorState } from '@/components/managed/shared'
import { Button } from '@/components/ui/button'
import { managedGet } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import { parseCredentialDetailResponse } from '@/lib/managed/credential-response-parsers'
import type { CredentialId } from '@/types/entity-id'

import { ModelConnectionDetail } from './model-connection-detail'
import { ServiceCredentialDetail } from './service-credential-detail'

export function CredentialDetail({ credentialId }: { credentialId: CredentialId }) {
  const { t } = useTranslation()
  const router = useRouter()
  const managedScope = useManagedRequestScope()

  const query = useQuery({
    queryKey: ['credential-detail', managedScope.key, credentialId],
    queryFn: async () => {
      const res = await managedGet<unknown>(
        apiResourcePath('credentials', credentialId),
        managedRequestOptions(managedScope),
      )
      return parseCredentialDetailResponse(res)
    },
    enabled: hasManagedRequestScope(managedScope),
  })

  const credential = query.data
  const redirectGroupId = credential?.kind === 'mcp' ? (credential.group_id ?? null) : null

  useEffect(() => {
    if (redirectGroupId) router.replace(`/managed/credentials/mcp/${redirectGroupId}`)
  }, [redirectGroupId, router])

  if (query.isError) {
    return (
      <ResourceErrorState
        error={query.error}
        resource="credential"
        onRetry={() => query.refetch()}
      />
    )
  }
  if (query.isLoading || !credential) {
    return (
      <div className="py-10 text-center text-sm text-muted-foreground">{t('common.loading')}</div>
    )
  }
  if (credential.kind === 'model') return <ModelConnectionDetail credential={credential} />
  if (credential.kind === 'service') return <ServiceCredentialDetail credential={credential} />
  if (credential.kind === 'mcp') {
    if (credential.group_id) {
      return (
        <div className="py-10 text-center text-sm text-muted-foreground">
          {t('managed.credentials.redirecting')}
        </div>
      )
    }
    return (
      <div className="flex min-h-[360px] flex-col items-center justify-center px-6 py-16 text-center">
        <p className="mb-6 max-w-md text-sm leading-6 text-muted-foreground">
          {t('managed.credentials.orphanCredential')}
        </p>
        <Button variant="outline" onClick={() => router.push('/managed/credentials?tab=mcp')}>
          <ArrowLeft className="mr-1 h-4 w-4" />
          {t('common.back')}
        </Button>
      </div>
    )
  }
  return (
    <ResourceErrorState
      resource="credential"
      reason="notFound"
      onBack={() => router.push('/managed/credentials')}
    />
  )
}
