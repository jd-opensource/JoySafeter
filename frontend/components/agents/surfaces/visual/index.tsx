import type { BuilderSurface, StageProps } from '@/components/agents/agent-build/agent-build-types'

function StubStage(_props: StageProps) {
  return <div>Visual stub — will be replaced</div>
}

export const visualSurface: BuilderSurface = {
  BriefStage: StubStage,
  BuildStage: StubStage,
  TestLabStage: StubStage,
}
