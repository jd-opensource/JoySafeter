'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import React, { useEffect } from 'react'

import { McpVaultDetail } from '@/components/managed/credentials/mcp-vault-detail'
import { withEntityRouteGuard } from '@/components/managed/shared'
import { parseCredentialGroupId } from '@/types/entity-id'

function McpVaultDetailPageInner({ params }: { params: Promise<{ credentialGroupId: string }> }) {
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
  return <McpVaultDetail credentialGroupId={parseCredentialGroupId(credentialGroupId)} autoOpenAddCredential={add} />
}

export default withEntityRouteGuard(McpVaultDetailPageInner, {
  kind: 'vault',
  idKind: 'credentialGroup',
  paramKey: 'credentialGroupId',
  backTo: '/managed/credentials?tab=mcp',
})
