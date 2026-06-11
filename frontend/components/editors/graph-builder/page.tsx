'use client'

import { useParams } from 'next/navigation'

import { useProjectContext } from '@/hooks/managed/use-project-context'

import AgentBuilder from './AgentBuilder'

/**
 * Agent detail page
 *
 * Main page for viewing and editing agent configuration
 *
 * Route: /managed/[projectId]/[agentId]
 */
export default function AgentPage() {
  const params = useParams()
  const agentId = params.agentId as string
  const { projectId } = useProjectContext()

  return <AgentBuilder key={agentId} agentId={agentId} projectId={projectId} />
}
