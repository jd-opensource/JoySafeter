import type { LlmEngineCapability } from '@/types/llm'
import type { Secret } from '@/types/managed'

const GENERAL_ENGINE_PRIORITY = ['native', 'claude_code', 'claude', 'codex', 'pi']
const CODING_ENGINE_PRIORITY = ['claude_code', 'codex', 'claude', 'native', 'pi']
const CODING_INTENT_PATTERNS = [
  /\b(code|repo|repository|git|bug|fix|test|debug|typescript|javascript|python|rust)\b/i,
  /代码|仓库|修复|测试|调试|报错|提交|构建/,
]

export type QuickstartEngineReadiness = 'ready' | 'setup_required' | 'unavailable'

export interface QuickstartEngineOption {
  engine: LlmEngineCapability
  engineId: string
  readiness: QuickstartEngineReadiness
  compatibleConnectionCount: number
  hasDefaultConnection: boolean
  recommended: boolean
}

interface BuildQuickstartEngineOptionsInput {
  enabledEngines: LlmEngineCapability[]
  modelConnections: Secret[]
  intentText: string
}

function priorityIndex(priority: string[], engineId: string): number {
  const index = priority.indexOf(engineId)
  return index >= 0 ? index : priority.length
}

export function buildQuickstartEngineOptions({
  enabledEngines,
  modelConnections,
  intentText,
}: BuildQuickstartEngineOptionsInput): QuickstartEngineOption[] {
  const priority = CODING_INTENT_PATTERNS.some((pattern) => pattern.test(intentText))
    ? CODING_ENGINE_PRIORITY
    : GENERAL_ENGINE_PRIORITY
  const activeConnections = modelConnections.filter((connection) => !connection.archived_at)

  const options = enabledEngines.map((engine) => {
    const compatibleConnections = activeConnections.filter((connection) =>
      connection.compatible_engine_ids.includes(engine.id),
    )
    return {
      engine,
      engineId: engine.id,
      readiness: !engine.enabled
        ? ('unavailable' as const)
        : compatibleConnections.length > 0
          ? ('ready' as const)
          : ('setup_required' as const),
      compatibleConnectionCount: compatibleConnections.length,
      hasDefaultConnection: compatibleConnections.some((connection) => connection.is_default),
      recommended: false,
    }
  })

  options.sort((left, right) => {
    const readinessRank = { ready: 0, setup_required: 1, unavailable: 2 } as const
    const readinessDifference = readinessRank[left.readiness] - readinessRank[right.readiness]
    if (readinessDifference !== 0) return readinessDifference

    const priorityDifference =
      priorityIndex(priority, left.engineId) - priorityIndex(priority, right.engineId)
    if (priorityDifference !== 0) return priorityDifference

    const defaultDifference = Number(right.hasDefaultConnection) - Number(left.hasDefaultConnection)
    if (defaultDifference !== 0) return defaultDifference

    return left.engine.display_name.localeCompare(right.engine.display_name)
  })

  const recommendedIndex = options.findIndex((option) => option.readiness !== 'unavailable')
  return options.map((option, index) => ({ ...option, recommended: index === recommendedIndex }))
}
