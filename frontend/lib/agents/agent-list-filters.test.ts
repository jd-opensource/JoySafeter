import { describe, expect, it } from 'vitest'

import type { Agent } from '@/types/agent'

import {
  AGENT_LIST_DEFINITION_FILTERS,
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
    definition_kind: null,
    runtime_kind: null,
    created_by: 'user-1',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('agent list filters', () => {
  it('exposes only supported product definition filters', () => {
    expect(AGENT_LIST_DEFINITION_FILTERS.map((option) => option.value)).toEqual([
      'all',
      'graph',
      'code',
      'claude_code',
      'codex',
      'openclaw',
    ])
  })

  it('exposes only supported runtime filters', () => {
    expect(AGENT_LIST_RUNTIME_FILTERS.map((option) => option.value)).toEqual([
      'all',
      'graph',
      'code',
      'sandbox',
    ])
  })

  it('filters by definition kind and runtime kind', () => {
    const graphAgent = makeAgent({ id: 'graph', definition_kind: 'graph', runtime_kind: 'graph' })
    const codexAgent = makeAgent({ id: 'codex', definition_kind: 'codex', runtime_kind: 'sandbox' })
    const codeDraft = makeAgent({ id: 'code', definition_kind: 'code', runtime_kind: null })

    expect(
      filterAgentsForList([graphAgent, codexAgent, codeDraft], {
        definitionKind: 'codex',
        runtimeKind: 'all',
      }).map((agent) => agent.id),
    ).toEqual(['codex'])

    expect(
      filterAgentsForList([graphAgent, codexAgent, codeDraft], {
        definitionKind: 'all',
        runtimeKind: 'sandbox',
      }).map((agent) => agent.id),
    ).toEqual(['codex'])

    expect(
      filterAgentsForList([graphAgent, codexAgent, codeDraft], {
        definitionKind: 'code',
        runtimeKind: 'sandbox',
      }),
    ).toEqual([])
  })
})
