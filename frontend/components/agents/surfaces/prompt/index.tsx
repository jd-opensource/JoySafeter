import type { BuilderSurface, StageProps } from '@/components/agents/agent-build/agent-build-types'

function PlaceholderStage(_props: StageProps) {
  return (
    <div className="flex h-full items-center justify-center text-sm text-[var(--text-muted)]">
      Prompt Builder — coming soon
    </div>
  )
}

export const promptSurface: BuilderSurface = {
  BriefStage: PlaceholderStage,
  BuildStage: PlaceholderStage,
  TestLabStage: PlaceholderStage,
}
