import { describe, expect, it } from 'vitest'

import { normalizeMcpServerUrl, summarizeMcpCredentialCoverage } from './mcp-credential-coverage'

describe('normalizeMcpServerUrl', () => {
  it('matches the backend canonical URL contract', () => {
    expect(normalizeMcpServerUrl(' HTTPS://MCP.Example.COM:443/api/#fragment ')).toBe(
      'https://mcp.example.com/api',
    )
    expect(normalizeMcpServerUrl('http://MCP.Example.COM:80/?b=2&a=1')).toBe(
      'http://mcp.example.com?b=2&a=1',
    )
    expect(normalizeMcpServerUrl('https://mcp.example.com/api//')).toBe(
      'https://mcp.example.com/api/',
    )
  })

  it('returns trimmed invalid values unchanged', () => {
    expect(normalizeMcpServerUrl('  not-a-url  ')).toBe('not-a-url')
    expect(normalizeMcpServerUrl(undefined)).toBe('')
  })
})

describe('summarizeMcpCredentialCoverage', () => {
  it('classifies required, optional, none, ambiguous, and unrelated credentials', () => {
    const summary = summarizeMcpCredentialCoverage(
      [
        {
          type: 'streamable_http',
          name: 'required-ok',
          url: 'https://required.example.com/mcp/',
          auth_requirement: 'required',
        },
        {
          type: 'streamable_http',
          name: 'required-missing',
          url: 'https://missing.example.com/mcp',
          auth_requirement: 'required',
        },
        {
          type: 'streamable_http',
          name: 'optional-anonymous',
          url: 'https://optional.example.com/mcp',
          auth_requirement: 'optional',
        },
        {
          type: 'streamable_http',
          name: 'ambiguous',
          url: 'https://duplicate.example.com/mcp',
          auth_requirement: 'optional',
        },
        {
          type: 'sse',
          name: 'public-events',
          url: 'https://events.example.com/sse',
          auth_requirement: 'none',
        },
        { type: 'local_stdio', name: 'local', command: 'node', args: [], env: {} },
      ],
      [
        { mcp_server_url: 'HTTPS://REQUIRED.example.com:443/mcp' },
        { mcp_server_url: 'https://duplicate.example.com/mcp' },
        { mcp_server_url: 'https://duplicate.example.com/mcp/' },
        { mcp_server_url: 'https://unrelated.example.com/mcp' },
        { mcp_server_url: 'https://required.example.com/mcp', archived_at: '2026-08-01' },
      ],
    )

    expect(summary.endpoints.map(({ name, status }) => ({ name, status }))).toEqual([
      { name: 'required-ok', status: 'matched' },
      { name: 'required-missing', status: 'missing_required' },
      { name: 'optional-anonymous', status: 'optional_anonymous' },
      { name: 'ambiguous', status: 'ambiguous' },
      { name: 'public-events', status: 'not_required' },
    ])
    expect(summary.blocking).toBe(true)
  })
})
