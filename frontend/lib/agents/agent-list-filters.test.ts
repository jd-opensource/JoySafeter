import { describe, expect, it } from 'vitest'

import type { Agent } from '@/types/agent'

import {
  AGENT_LIST_ENGINE_FILTERS,
  AGENT_LIST_RUNTIME_FILTERS,
  filterAgentsForList,
} from './agent-list-filters'

function makeAgent(overrides: Partial<Agent>): Agent {
  return {
    id: overrides.id ?? 'agent-1',
    workspace_id: 'workspace-1',
    name: 'Agent',
    slug: 'agent',
    description: null,
    avatar: null,
    status: 'draft',
    has_custom_env: false,
    current_draft_version_id: 'version-1',
    active_release_id: null,
    engine_kind: null,
    runtime_kind: null,
    created_by: 'user-1',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('agent list filters', () => {
  it('exposes only supported product engine filters', () => {
    expect(AGENT_LIST_ENGINE_FILTERS.map((option) => option.value)).toEqual([
      'all',
      'langgraph_visual',
      'langgraph_code',
      'claude_code',
      'codex',
      'openclaw',
    ])
  })

  it('exposes only supported runtime filters', () => {
    expect(AGENT_LIST_RUNTIME_FILTERS.map((option) => option.value)).toEqual([
      'all',
      'sandbox',
      'server',
    ])
  })

  it('filters by engine kind and runtime kind', () => {
    const graphAgent = makeAgent({ id: 'graph', engine_kind: 'langgraph_visual', runtime_kind: 'server' })
    const codexAgent = makeAgent({ id: 'codex', engine_kind: 'codex', runtime_kind: 'sandbox' })
    const codeDraft = makeAgent({ id: 'code', engine_kind: 'langgraph_code', runtime_kind: null })

    expect(
      filterAgentsForList([graphAgent, codexAgent, codeDraft], {
        engineKind: 'codex',
        runtimeKind: 'all',
      }).map((agent) => agent.id),
    ).toEqual(['codex'])

    expect(
      filterAgentsForList([graphAgent, codexAgent, codeDraft], {
        engineKind: 'all',
        runtimeKind: 'sandbox',
      }).map((agent) => agent.id),
    ).toEqual(['codex'])

    expect(
      filterAgentsForList([graphAgent, codexAgent, codeDraft], {
        engineKind: 'langgraph_code',
        runtimeKind: 'sandbox',
      }),
    ).toEqual([])
  })
})
