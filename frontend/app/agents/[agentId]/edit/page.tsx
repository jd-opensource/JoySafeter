'use client'

import { useParams, useRouter } from 'next/navigation'
import { useEffect } from 'react'

export default function AgentEditRedirect() {
  const params = useParams()
  const router = useRouter()
  const agentId = params.agentId as string

  useEffect(() => {
    router.replace(`/agents/${agentId}?tab=settings`)
  }, [agentId, router])

  return null
}
