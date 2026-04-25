'use client'

import type { BuildStageId, BuilderSurface, StageProps } from './agent-build-types'
import { AgentReleaseStage } from './agent-release-stage'
import { AgentUsageStage } from './agent-usage-stage'

interface StageRendererProps {
  stageId: BuildStageId
  surface: BuilderSurface
  stageProps: StageProps
}

export function StageRenderer({ stageId, surface, stageProps }: StageRendererProps) {
  switch (stageId) {
    case 'brief':
      return <surface.BriefStage {...stageProps} />
    case 'build':
      return <surface.BuildStage {...stageProps} />
    case 'test-lab':
      return <surface.TestLabStage {...stageProps} />
    case 'release':
      return <AgentReleaseStage {...stageProps} />
    case 'usage':
      return <AgentUsageStage {...stageProps} />
  }
}
