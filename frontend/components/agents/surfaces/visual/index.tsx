import type { BuilderSurface } from '@/components/agents/agent-build/agent-build-types'

import { VisualBriefStage } from './visual-brief-stage'
import { VisualBuilderSurface } from './visual-builder-surface'
import { VisualTestLabStage } from './visual-test-lab-stage'

export const visualSurface: BuilderSurface = {
  BriefStage: VisualBriefStage,
  BuildStage: VisualBuilderSurface,
  TestLabStage: VisualTestLabStage,
}
