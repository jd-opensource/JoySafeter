import { describe, expect, it, vi } from 'vitest'

import { managedPost } from '@/lib/api-client'

import {
  parseQuickstartRecommendation,
  fetchQuickstartRecommendation,
} from './quickstart-recommendation-client'

vi.mock('@/lib/api-client', () => ({ managedPost: vi.fn() }))
vi.mock('@/lib/managed/request-scope', () => ({
  managedRequestOptions: () => ({}),
}))

describe('parseQuickstartRecommendation', () => {
  it('parses a secure recommendation', () => {
    const rec = parseQuickstartRecommendation({
      phase: 'secure',
      environment: {
        allowed_hosts: ['github.com', 'api.github.com'],
        host_reason: 'knownServices',
      },
      credential_group: null,
    })
    expect(rec.phase).toBe('secure')
    expect(rec.environment.allowed_hosts).toEqual(['github.com', 'api.github.com'])
  })

  it('parses an understand recommendation with engine options', () => {
    const rec = parseQuickstartRecommendation({
      phase: 'understand',
      engine: {
        recommended_engine_id: 'claude',
        options: [
          { engine_id: 'claude', readiness: 'setup_required', compatible_connection_count: 0 },
        ],
      },
    })
    expect(rec.engine.recommended_engine_id).toBe('claude')
    expect(rec.engine.options[0].readiness).toBe('setup_required')
  })

  it('parses every recommended MCP server and preserves its auth requirement', () => {
    const rec = parseQuickstartRecommendation({
      phase: 'secure',
      environment: {
        allowed_hosts: ['mcp.acme.io', 'public.example.org'],
        host_reason: 'explicitHosts',
      },
      credential_group: {
        mcp_servers: [
          {
            name: 'Acme',
            url: 'https://mcp.acme.io/sse',
            auth_requirement: 'required',
          },
          {
            name: 'Optional',
            url: 'https://optional.example.org/mcp',
            auth_requirement: 'optional',
          },
        ],
        external_tools_reason: 'mcpServers',
      },
    })

    expect(rec.credential_group?.mcp_servers).toHaveLength(2)
    expect(rec.credential_group?.mcp_servers[1].auth_requirement).toBe('optional')
  })

  it('rejects malformed or incomplete responses instead of fabricating defaults', () => {
    expect(() => parseQuickstartRecommendation({ phase: 'weird', engine: 'nope' })).toThrow()
    expect(() =>
      parseQuickstartRecommendation({
        phase: 'secure',
        environment: { allowed_hosts: [], host_reason: 'none' },
        credential_group: null,
        engine: { recommended_engine_id: null, options: [] },
      }),
    ).toThrow()
  })

  it('rejects inconsistent semantic combinations', () => {
    expect(() =>
      parseQuickstartRecommendation({
        phase: 'understand',
        engine: null,
        environment: { allowed_hosts: [], host_reason: 'none' },
      }),
    ).toThrow()
    expect(() =>
      parseQuickstartRecommendation({
        phase: 'secure',
        environment: { allowed_hosts: [], host_reason: 'none' },
        credential_group: { mcp_servers: [], external_tools_reason: 'mcpServers' },
      }),
    ).toThrow()
  })

  it('rejects recommended MCP URLs outside the canonical HTTP transports', () => {
    expect(() =>
      parseQuickstartRecommendation({
        phase: 'secure',
        environment: { allowed_hosts: [], host_reason: 'none' },
        credential_group: {
          mcp_servers: [
            {
              name: 'unsafe',
              url: 'ftp://example.com/mcp',
              auth_requirement: 'required',
            },
          ],
          external_tools_reason: 'mcpServers',
        },
      }),
    ).toThrow()
  })
})

describe('fetchQuickstartRecommendation', () => {
  it('posts to the recommendations route and returns a parsed recommendation', async () => {
    vi.mocked(managedPost).mockResolvedValueOnce({
      phase: 'secure',
      environment: {
        allowed_hosts: [],
        host_reason: 'none',
      },
      credential_group: null,
    })
    const rec = await fetchQuickstartRecommendation({ phase: 'secure', intent: 'do a thing' }, {
      key: 'org:proj',
    } as never)
    expect(managedPost).toHaveBeenCalledWith(
      'quickstart/recommendations',
      { phase: 'secure', intent: 'do a thing' },
      {},
    )
    expect(rec.phase).toBe('secure')
    expect(rec.environment.allowed_hosts).toEqual([])
  })
})
