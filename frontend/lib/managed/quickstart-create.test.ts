import { describe, expect, it } from 'vitest'

import { buildQuickstartAgentCreateBody } from './quickstart-create'

describe('buildQuickstartAgentCreateBody', () => {
  it('preserves generated agent config fields accepted by the backend schema', () => {
    const body = buildQuickstartAgentCreateBody(
      {
        name: 'Research Agent',
        description: 'Finds and summarizes sources',
        system_prompt: 'You research carefully.',
        model: { id: 'claude-sonnet-4', speed: 'standard' },
        tools: [{ type: 'agent_toolset_20260401' }],
        mcp_servers: [{ type: 'url', name: 'docs', url: 'https://docs.example.com/mcp' }],
        skills: [{ type: 'custom', skill_id: 'skill_123', version: 'latest' }],
        env: { FEATURE_FLAG: '1' },
        multiagent: { enabled: true },
        metadata: { topic: 'security' },
      },
      {
        engineKind: 'claude',
        secretRef: 'anthropic-prod',
        suffix: '-abcd',
      },
    )

    expect(body).toEqual({
      name: 'Research Agent-abcd',
      engine_kind: 'claude',
      description: 'Finds and summarizes sources',
      system_prompt: 'You research carefully.',
      model: { id: 'claude-sonnet-4', speed: 'standard' },
      secret_ref: 'anthropic-prod',
      tools: [{ type: 'agent_toolset_20260401' }],
      mcp_servers: [{ type: 'url', name: 'docs', url: 'https://docs.example.com/mcp' }],
      skills: [{ type: 'custom', skill_id: 'skill_123', version: 'latest' }],
      env: { FEATURE_FLAG: '1' },
      multiagent: { enabled: true },
      metadata: { topic: 'security' },
    })
  })

  it('keeps previous defaults for minimal generated configs', () => {
    expect(
      buildQuickstartAgentCreateBody(
        { name: 'Minimal', system: 'Do the task.' },
        { engineKind: 'codex', secretRef: 'openai-prod', suffix: '' },
      ),
    ).toEqual({
      name: 'Minimal',
      engine_kind: 'codex',
      system_prompt: 'Do the task.',
      secret_ref: 'openai-prod',
      tools: [],
    })
  })
})
