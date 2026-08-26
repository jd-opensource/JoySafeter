'use client'

import React from 'react'

import { CredentialDetail } from '@/components/managed/credentials/credential-detail'
import { withEntityRouteGuard } from '@/components/managed/shared'
import { parseCredentialId } from '@/types/entity-id'

function CredentialDetailPageInner({ params }: { params: Promise<{ credentialId: string }> }) {
  const { credentialId } = React.use(params)
  return <CredentialDetail credentialId={parseCredentialId(credentialId)} />
}

export default withEntityRouteGuard(CredentialDetailPageInner, {
  kind: 'credential',
  idKind: 'credential',
  paramKey: 'credentialId',
  backTo: '/managed/credentials',
})
