import { cliSurface } from '@/components/agents/surfaces/cli'
import { codeSurface } from '@/components/agents/surfaces/code'
import { visualSurface } from '@/components/agents/surfaces/visual'
import { ENGINE_KINDS } from '@/types/agent'

import type { BuilderSurface } from './agent-build-types'
import type { EngineKind } from '@/types/agent'

export type BuilderSurfaceKind = 'visual' | 'cli' | 'code'

const SURFACE_MAP: Record<BuilderSurfaceKind, BuilderSurface> = {
  visual: visualSurface,
  cli: cliSurface,
  code: codeSurface,
}

const ENGINE_TO_SURFACE: Record<EngineKind, BuilderSurfaceKind> = {
  langgraph_visual: 'visual',
  langgraph_code: 'code',
  claude_code: 'cli',
  codex: 'cli',
  native: 'cli',
}

export function resolveBuilderSurface(engineKind: string | null | undefined): BuilderSurface {
  const surfaceKind = isEngineKind(engineKind) ? ENGINE_TO_SURFACE[engineKind] : 'visual'

  return SURFACE_MAP[surfaceKind]
}

function isEngineKind(engineKind: string | null | undefined): engineKind is EngineKind {
  return ENGINE_KINDS.includes(engineKind as EngineKind)
}
