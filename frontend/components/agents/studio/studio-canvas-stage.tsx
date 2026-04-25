'use client'

import AgentBuilder from '@/components/editors/graph-builder/AgentBuilder'

interface StudioCanvasStageProps {
  agentId: string
  workspaceId: string
  versionId?: string
  onOpenTestLab: () => void
  onOpenRelease: () => void
}

export function StudioCanvasStage({
  agentId,
  workspaceId,
  versionId,
  onOpenTestLab,
  onOpenRelease,
}: StudioCanvasStageProps) {
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
