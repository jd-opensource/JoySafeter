'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import React, { useEffect } from 'react'

import { McpCredentialGroupDetail } from '@/components/managed/credentials/mcp-vault-detail'
import { withEntityRouteGuard } from '@/components/managed/shared'
import { parseCredentialGroupId } from '@/types/entity-id'

function McpCredentialGroupDetailPageInner({
  params,
}: {
  params: Promise<{ credentialGroupId: string }>
}) {
  const { credentialGroupId } = React.use(params)
  const router = useRouter()
  const searchParams = useSearchParams()
  const add = searchParams.get('add') === '1'
  useEffect(() => {
    if (!add) return
    const next = new URLSearchParams(searchParams.toString())
    next.delete('add')
    const qs = next.toString()
    router.replace(`/managed/credentials/mcp/${credentialGroupId}${qs ? `?${qs}` : ''}`)
  }, [add, credentialGroupId, router, searchParams])
  return (
    <McpCredentialGroupDetail
      credentialGroupId={parseCredentialGroupId(credentialGroupId)}
      autoOpenAddCredential={add}
    />
  )
}

export default withEntityRouteGuard(McpCredentialGroupDetailPageInner, {
  kind: 'vault',
  idKind: 'credentialGroup',
  paramKey: 'credentialGroupId',
  backTo: '/managed/credentials?tab=mcp',
})
