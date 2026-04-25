'use client'

import { useAgent } from '@/hooks/queries/agents'
import { useCurrentWorkspace } from '@/providers/workspace-provider'
import AgentBuilder from '@/components/editors/graph-builder/AgentBuilder'

interface AgentBuilderTabProps {
  agentId: string
}

export function AgentBuilderTab({ agentId }: AgentBuilderTabProps) {
  const { workspaceId } = useCurrentWorkspace()

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
