'use client'

import AgentBuilder from '@/components/editors/graph-builder/AgentBuilder'

interface VisualBuilderSurfaceProps {
  agentId: string
  workspaceId: string
  versionId?: string
  onOpenTestLab: () => void
  onOpenRelease: () => void
}

export function VisualBuilderSurface({
  agentId,
  workspaceId,
  versionId,
  onOpenTestLab,
  onOpenRelease,
}: VisualBuilderSurfaceProps) {
  return (
    <AgentBuilder
      workspaceId={workspaceId}
      agentId={agentId}
      versionId={versionId}
      studioMode
      onOpenTestLab={onOpenTestLab}
      onOpenRelease={onOpenRelease}
    />
  )
}
