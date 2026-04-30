import type { Agent, EngineKind, RuntimeKind } from '@/types/agent'

export type AgentListEngineFilter = 'all' | EngineKind
export type AgentListRuntimeFilter = 'all' | RuntimeKind

export interface AgentListFilterOption<T extends string> {
  value: T
  labelKey: string
  defaultLabel: string
}

export const AGENT_LIST_ENGINE_FILTERS: readonly AgentListFilterOption<AgentListEngineFilter>[] = [
  { value: 'all', labelKey: 'agents.filters.allBuildTypes', defaultLabel: 'All build types' },
  { value: 'langgraph_visual', labelKey: 'agents.graph.shortLabel', defaultLabel: 'Graph' },
  { value: 'langgraph_code', labelKey: 'agents.code.shortLabel', defaultLabel: 'Code' },
  { value: 'claude_code', labelKey: 'agents.claudeCode.shortLabel', defaultLabel: 'Claude Code' },
  { value: 'codex', labelKey: 'agents.codex.shortLabel', defaultLabel: 'Codex' },
  { value: 'openclaw', labelKey: 'agents.openclaw.shortLabel', defaultLabel: 'OpenClaw' },
] as const

export const AGENT_LIST_RUNTIME_FILTERS: readonly AgentListFilterOption<AgentListRuntimeFilter>[] = [
  { value: 'all', labelKey: 'agents.filters.allRuntimeTypes', defaultLabel: 'All runtime types' },
  { value: 'sandbox', labelKey: 'agents.runtime.sandbox', defaultLabel: 'Sandbox' },
  { value: 'server', labelKey: 'agents.runtime.server', defaultLabel: 'Server' },
] as const

export function filterAgentsForList(
  agents: readonly Agent[],
  filters: {
    engineKind: AgentListEngineFilter
    runtimeKind: AgentListRuntimeFilter
  },
): Agent[] {
  return agents.filter((agent) => {
    const matchesEngine =
      filters.engineKind === 'all' || agent.engine_kind === filters.engineKind
    const matchesRuntime =
      filters.runtimeKind === 'all' || agent.runtime_kind === filters.runtimeKind
    return matchesEngine && matchesRuntime
  })
}
