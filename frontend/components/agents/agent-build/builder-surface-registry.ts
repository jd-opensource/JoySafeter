import { cliSurface } from '@/components/agents/surfaces/cli'
import { codeSurface } from '@/components/agents/surfaces/code'
import { visualSurface } from '@/components/agents/surfaces/visual'

import type { BuilderSurface } from './agent-build-types'

export type BuilderSurfaceKind = 'visual' | 'cli' | 'code'

const SURFACE_MAP: Record<BuilderSurfaceKind, BuilderSurface> = {
  visual: visualSurface,
  cli:    cliSurface,
  code:   codeSurface,
}

const DEFINITION_TO_SURFACE: Record<string, BuilderSurfaceKind> = {
  graph:       'visual',
  code:        'code',
  claude_code: 'cli',
  codex:       'cli',
  openclaw:    'cli',
}

export function resolveBuilderSurface(definitionKind: string | null | undefined): BuilderSurface {
  const surfaceKind = DEFINITION_TO_SURFACE[definitionKind ?? ''] ?? 'visual'
  return SURFACE_MAP[surfaceKind]
}
