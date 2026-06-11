import type { BuilderSurface, StageProps } from '@/components/agents/agent-build/agent-build-types'

function PlaceholderStage(_props: StageProps) {
  return (
    <div className="flex h-full items-center justify-center text-sm text-[var(--text-muted)]">
      Claude Code / Codex builder coming soon
    </div>
  )
}

export const cliSurface: BuilderSurface = {
  BriefStage: PlaceholderStage,
  BuildStage: PlaceholderStage,
  TestLabStage: PlaceholderStage,
}
