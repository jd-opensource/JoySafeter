import type { BuilderSurface, StageProps } from '@/components/agents/agent-build/agent-build-types'

function PlaceholderStage(_props: StageProps) {
  return (
    <div className="flex h-full items-center justify-center text-sm text-[var(--text-muted)]">
      Code Builder — coming soon
    </div>
  )
}

export const codeSurface: BuilderSurface = {
  BriefStage: PlaceholderStage,
  BuildStage: PlaceholderStage,
  TestLabStage: PlaceholderStage,
}
