'use client'

import { useParams, useRouter } from 'next/navigation'
import { useEffect } from 'react'

export default function AgentVersionsRedirect() {
  const params = useParams()
  const router = useRouter()
  const agentId = params.agentId as string

  useEffect(() => {
    router.replace(`/agents/${agentId}/build?tab=drafts`)
  }, [agentId, router])

  return null
}
