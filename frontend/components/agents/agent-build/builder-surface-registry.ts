export type BuilderSurfaceKind = 'visual' | 'cli' | 'code' | 'prompt'

const BUILDER_SURFACE_KINDS = new Set<BuilderSurfaceKind>([
  'visual',
  'cli',
  'code',
  'prompt',
])

const DEFINITION_KIND_TO_SURFACE: Record<string, BuilderSurfaceKind> = {
  graph: 'visual',
  code: 'code',
  prompt: 'prompt',
  cli: 'cli',
}

export function isBuilderSurfaceKind(
  value: string | null | undefined
): value is BuilderSurfaceKind {
  return BUILDER_SURFACE_KINDS.has(value as BuilderSurfaceKind)
}

export function getBuilderSurfaceKind(
  definitionKind: string | null | undefined
): BuilderSurfaceKind {
  if (!definitionKind) {
    return 'visual'
  }

  return DEFINITION_KIND_TO_SURFACE[definitionKind] ?? 'visual'
}
