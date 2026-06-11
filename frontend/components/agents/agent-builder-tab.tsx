'use client'

// Compatibility wrapper for legacy ?tab=builder links. Visual Agents now use AgentStudioShell by default.

import { useAgent } from '@/hooks/queries/agents'
import { useProjectContext } from '@/hooks/managed/use-project-context'
import AgentBuilder from '@/components/editors/graph-builder/AgentBuilder'

interface AgentBuilderTabProps {
  agentId: string
}

export function AgentBuilderTab({ agentId }: AgentBuilderTabProps) {
  const { projectId } = useProjectContext()

  const { data: agent } = useAgent(agentId, projectId)

  if (!agent) return null

  return (
    <div className="h-full">
      <AgentBuilder
        projectId={projectId}
        agentId={agentId}
        versionId={agent.current_draft_version_id || undefined}
      />
    </div>
  )
}
