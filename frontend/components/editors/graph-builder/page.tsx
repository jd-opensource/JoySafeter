'use client'

import { useParams } from 'next/navigation'

import { useCurrentWorkspace } from '@/providers/workspace-provider'

import AgentBuilder from './AgentBuilder'

/**
 * Agent detail page
 *
 * Main page for viewing and editing agent configuration
 *
 * Route: /workspace/[workspaceId]/[agentId]
 */
export default function AgentPage() {
  const params = useParams()
  const agentId = params.agentId as string
  const { workspaceId } = useCurrentWorkspace()

  return <AgentBuilder key={agentId} agentId={agentId} workspaceId={workspaceId} />
}
