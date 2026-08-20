import { objectValue } from '@/lib/managed/quickstart-value-coercion'

export type QuickstartGenerationPhase =
  | 'understanding'
  | 'responsibilities'
  | 'boundaries'
  | 'tools'
  | 'instructions'
  | 'acceptance'

const PHASE_ORDER: QuickstartGenerationPhase[] = [
  'understanding',
  'responsibilities',
  'boundaries',
  'tools',
  'instructions',
  'acceptance',
]

function hasContent(value: unknown): boolean {
  if (typeof value === 'string') return Boolean(value.trim())
  if (Array.isArray(value)) return value.length > 0
  const object = objectValue(value)
  return Boolean(object && Object.keys(object).length)
}

function laterPhase(
  left: QuickstartGenerationPhase,
  right: QuickstartGenerationPhase,
): QuickstartGenerationPhase {
  return PHASE_ORDER.indexOf(left) >= PHASE_ORDER.indexOf(right) ? left : right
}

export function quickstartGenerationPhaseForElapsed(
  elapsedSeconds: number,
): QuickstartGenerationPhase {
  if (elapsedSeconds >= 14) return 'acceptance'
  if (elapsedSeconds >= 11) return 'instructions'
  if (elapsedSeconds >= 8) return 'tools'
  if (elapsedSeconds >= 5) return 'boundaries'
  if (elapsedSeconds >= 2) return 'responsibilities'
  return 'understanding'
}

export function inferQuickstartGenerationPhase({
  elapsedSeconds,
  agentConfig,
}: {
  elapsedSeconds: number
  agentConfig?: Record<string, unknown>
}): QuickstartGenerationPhase {
  let phase = quickstartGenerationPhaseForElapsed(elapsedSeconds)
  const blueprint = objectValue(agentConfig?.blueprint)
  if (!blueprint) return phase

  if (hasContent(blueprint.responsibilities) || hasContent(blueprint.workflow)) {
    phase = laterPhase(phase, 'responsibilities')
  }
  if (hasContent(blueprint.boundaries)) phase = laterPhase(phase, 'boundaries')
  if (hasContent(blueprint.toolPlan) || hasContent(blueprint.tool_plan)) {
    phase = laterPhase(phase, 'tools')
  }
  if (hasContent(blueprint.outputContract) || hasContent(blueprint.output_contract)) {
    phase = laterPhase(phase, 'instructions')
  }
  if (
    hasContent(blueprint.acceptanceTest) ||
    hasContent(blueprint.acceptance_test) ||
    hasContent(blueprint.successCriteria) ||
    hasContent(blueprint.success_criteria)
  ) {
    phase = 'acceptance'
  }
  return phase
}
