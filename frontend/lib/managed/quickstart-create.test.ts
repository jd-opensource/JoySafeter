import { describe, expect, it } from 'vitest'

import { buildQuickstartAgentCreateBody } from './quickstart-create'

describe('buildQuickstartAgentCreateBody', () => {
  it('preserves generated agent config fields accepted by the backend schema', () => {
    const body = buildQuickstartAgentCreateBody(
      {
        name: 'Research Agent',
        description: 'Finds and summarizes sources',
        system: 'You research carefully.',
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
      system: 'You research carefully.',
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
      system: 'Do the task.',
      secret_ref: 'openai-prod',
      tools: [],
    })
  })
})

describe('buildQuickstartAgentCreateBody with malformed generated config', () => {
  const opts = { engineKind: 'claude', secretRef: 'anthropic-prod', suffix: '' }

  it('drops a model object that is missing the required id', () => {
    const body = buildQuickstartAgentCreateBody(
      { name: 'A', model: { name: 'Claude', speed: 'fast' } },
      opts,
    )
    expect('model' in body).toBe(false)
  })

  it('drops model when it is neither a usable string nor an object with id', () => {
    expect('model' in buildQuickstartAgentCreateBody({ name: 'A', model: 123 }, opts)).toBe(false)
    expect('model' in buildQuickstartAgentCreateBody({ name: 'A', model: '   ' }, opts)).toBe(false)
    expect('model' in buildQuickstartAgentCreateBody({ name: 'A', model: {} }, opts)).toBe(false)
  })

  it('normalizes a model object to id and optional speed, trimming and dropping extras', () => {
    expect(
      buildQuickstartAgentCreateBody(
        { name: 'A', model: { id: '  claude-opus-4  ', junk: 'x' } },
        opts,
      ).model,
    ).toEqual({ id: 'claude-opus-4' })

    expect(
      buildQuickstartAgentCreateBody(
        { name: 'A', model: { id: 'claude-opus-4', speed: ' fast ' } },
        opts,
      ).model,
    ).toEqual({ id: 'claude-opus-4', speed: 'fast' })
  })

  it('coerces env values to strings and drops non-scalar entries', () => {
    const body = buildQuickstartAgentCreateBody(
      {
        name: 'A',
        env: {
          FLAG: 1,
          ENABLED: true,
          KEEP: 'ok',
          NULLED: null,
          NESTED: { x: 1 },
          LIST: [1, 2],
        },
      },
      opts,
    )
    expect(body.env).toEqual({ FLAG: '1', ENABLED: 'true', KEEP: 'ok' })
  })

  it('coerces metadata values the same way as env', () => {
    const body = buildQuickstartAgentCreateBody(
      { name: 'A', metadata: { count: 3, name: 'sec', bad: { nope: 1 } } },
      opts,
    )
    expect(body.metadata).toEqual({ count: '3', name: 'sec' })
  })

  it('omits env entirely when no value is coercible to a string', () => {
    const body = buildQuickstartAgentCreateBody(
      { name: 'A', env: { NESTED: { x: 1 }, NULLED: null } },
      opts,
    )
    expect('env' in body).toBe(false)
  })
})
