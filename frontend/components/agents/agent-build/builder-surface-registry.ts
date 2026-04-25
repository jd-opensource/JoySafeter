import type { BuilderSurface } from './agent-build-types'
import { visualSurface } from '@/components/agents/surfaces/visual'
import { cliSurface } from '@/components/agents/surfaces/cli'
import { codeSurface } from '@/components/agents/surfaces/code'
import { promptSurface } from '@/components/agents/surfaces/prompt'

export type BuilderSurfaceKind = 'visual' | 'cli' | 'code' | 'prompt'

const SURFACE_MAP: Record<BuilderSurfaceKind, BuilderSurface> = {
  visual: visualSurface,
  cli:    cliSurface,
  code:   codeSurface,
  prompt: promptSurface,
}

const DEFINITION_TO_SURFACE: Record<string, BuilderSurfaceKind> = {
  graph:  'visual',
  hybrid: 'visual',
  code:   'code',
  prompt: 'prompt',
  cli:    'cli',
}

export function resolveBuilderSurface(definitionKind: string | null | undefined): BuilderSurface {
  const surfaceKind = DEFINITION_TO_SURFACE[definitionKind ?? ''] ?? 'visual'
  return SURFACE_MAP[surfaceKind]
}
