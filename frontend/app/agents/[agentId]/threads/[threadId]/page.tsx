'use client'

import { useParams, useRouter } from 'next/navigation'
import { useEffect } from 'react'

export default function ThreadDetailRedirect() {
  const params = useParams()
  const router = useRouter()
  const agentId = params.agentId as string
  const threadId = params.threadId as string

  useEffect(() => {
    router.replace(`/agents/${agentId}?tab=chat&thread=${threadId}`)
  }, [agentId, threadId, router])

  return null
}
