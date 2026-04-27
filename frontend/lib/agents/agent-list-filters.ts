import type { Agent, DefinitionKind, RuntimeKind } from '@/types/agent'

export type AgentListDefinitionFilter = 'all' | DefinitionKind
export type AgentListRuntimeFilter = 'all' | RuntimeKind

export interface AgentListFilterOption<T extends string> {
  value: T
  labelKey: string
  defaultLabel: string
}

export const AGENT_LIST_DEFINITION_FILTERS: readonly AgentListFilterOption<AgentListDefinitionFilter>[] = [
  { value: 'all', labelKey: 'agents.filters.allBuildTypes', defaultLabel: 'All build types' },
  { value: 'graph', labelKey: 'agents.graph.shortLabel', defaultLabel: 'Graph' },
  { value: 'code', labelKey: 'agents.code.shortLabel', defaultLabel: 'Code' },
  { value: 'claude_code', labelKey: 'agents.claudeCode.shortLabel', defaultLabel: 'Claude Code' },
  { value: 'codex', labelKey: 'agents.codex.shortLabel', defaultLabel: 'Codex' },
  { value: 'openclaw', labelKey: 'agents.openclaw.shortLabel', defaultLabel: 'OpenClaw' },
] as const

export const AGENT_LIST_RUNTIME_FILTERS: readonly AgentListFilterOption<AgentListRuntimeFilter>[] = [
  { value: 'all', labelKey: 'agents.filters.allRuntimeTypes', defaultLabel: 'All runtime types' },
  { value: 'graph', labelKey: 'agents.runtime.graph', defaultLabel: 'Graph' },
  { value: 'code', labelKey: 'agents.runtime.code', defaultLabel: 'Code' },
  { value: 'sandbox', labelKey: 'agents.runtime.sandbox', defaultLabel: 'Sandbox' },
] as const

export function filterAgentsForList(
  agents: readonly Agent[],
  filters: {
    definitionKind: AgentListDefinitionFilter
    runtimeKind: AgentListRuntimeFilter
  },
): Agent[] {
  return agents.filter((agent) => {
    const matchesDefinition =
      filters.definitionKind === 'all' || agent.definition_kind === filters.definitionKind
    const matchesRuntime =
      filters.runtimeKind === 'all' || agent.runtime_kind === filters.runtimeKind
    return matchesDefinition && matchesRuntime
  })
}
