'use client'

import AgentBuilder from '@/components/editors/graph-builder/AgentBuilder'
import type { StageProps } from '@/components/agents/agent-build/agent-build-types'

export function VisualBuilderSurface({ agent, version, workspaceId }: StageProps) {
  return (
    <AgentBuilder
      agentId={agent.id}
      workspaceId={workspaceId}
      versionId={version?.id}
    />
  )
}
