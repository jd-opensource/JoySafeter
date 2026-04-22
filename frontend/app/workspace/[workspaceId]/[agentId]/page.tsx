'use client'

import { useParams, redirect } from 'next/navigation'
import { useEffect } from 'react'

/**
 * Legacy agent detail page - redirects to new location
 *
 * Old route: /workspace/[workspaceId]/[agentId]
 * New route: /agents/[agentId]/edit
 */
export default function LegacyAgentPage() {
  const params = useParams()
  const agentId = params.agentId as string

  useEffect(() => {
    if (agentId) {
      redirect(`/agents/${agentId}/edit`)
    }
  }, [agentId])

  return null
}
