'use client'

import { useAgent } from '@/hooks/queries/agents'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import AgentBuilder from '@/components/editors/graph-builder/AgentBuilder'

interface AgentBuilderTabProps {
  agentId: string
}

export function AgentBuilderTab({ agentId }: AgentBuilderTabProps) {
  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: agent } = useAgent(agentId, workspaceId)

  if (!agent) return null

  return (
    <div className="h-full">
      <AgentBuilder
        workspaceId={workspaceId}
        agentId={agentId}
        versionId={agent.current_draft_version_id || undefined}
      />
    </div>
  )
}
