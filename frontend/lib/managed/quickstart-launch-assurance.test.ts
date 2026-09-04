import { describe, expect, it } from 'vitest'

import { deriveQuickstartLaunchAssurance } from './quickstart-launch-assurance'

describe('deriveQuickstartLaunchAssurance', () => {
  it('reports enforced and ready controls without overstating optional authorization', () => {
    expect(
      deriveQuickstartLaunchAssurance({
        hasRuntime: true,
        hasModelConnection: true,
        environment: {
          id: 'env_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111',
          name: 'locked-down',
          config: { networking: { type: 'limited', allowed_hosts: ['api.github.com'] } },
          created_at: '',
          updated_at: '',
        },
        recommendedHosts: ['api.github.com'],
        mcpServers: [
          {
            type: 'streamable_http',
            name: 'GitHub',
            url: 'https://api.github.com/mcp',
            auth_requirement: 'required',
          },
        ],
        credentialGroupMembers: [{ mcp_server_url: 'https://api.github.com/mcp' }],
      }),
    ).toEqual({
      runtime: 'ready',
      modelConnection: 'ready',
      environment: 'enforced',
      externalTools: 'ready',
      audit: 'automatic',
      requiredHosts: ['api.github.com'],
      needsHardening: false,
    })
  })

  it('distinguishes recommended hardening from tools that are not authorized', () => {
    expect(
      deriveQuickstartLaunchAssurance({
        hasRuntime: true,
        hasModelConnection: true,
        environment: null,
        recommendedHosts: ['api.github.com'],
        mcpServers: [
          {
            type: 'streamable_http',
            name: 'GitHub',
            url: 'https://api.github.com/mcp',
            auth_requirement: 'required',
          },
        ],
        credentialGroupMembers: [],
      }),
    ).toEqual({
      runtime: 'ready',
      modelConnection: 'ready',
      environment: 'recommended',
      externalTools: 'not_authorized',
      audit: 'automatic',
      requiredHosts: ['api.github.com'],
      needsHardening: true,
    })
  })

  it('does not call an unrestricted or incomplete environment enforced', () => {
    const base = {
      hasRuntime: true,
      hasModelConnection: true,
      recommendedHosts: ['api.github.com'],
      mcpServers: [],
      credentialGroupMembers: [],
    }

    expect(
      deriveQuickstartLaunchAssurance({
        ...base,
        environment: {
          id: 'env_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111',
          name: 'open',
          config: { networking: { type: 'unrestricted', allowed_hosts: [] } },
          created_at: '',
          updated_at: '',
        },
      }).environment,
    ).toBe('recommended')
    expect(
      deriveQuickstartLaunchAssurance({
        ...base,
        environment: {
          id: 'env_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111',
          name: 'partial',
          config: { networking: { type: 'limited', allowed_hosts: [] } },
          created_at: '',
          updated_at: '',
        },
      }).environment,
    ).toBe('recommended')
  })

  it('requires authorization coverage for every required MCP server', () => {
    const result = deriveQuickstartLaunchAssurance({
      hasRuntime: true,
      hasModelConnection: true,
      environment: {
        id: 'env_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111',
        name: 'locked-down',
        config: {
          networking: {
            type: 'limited',
            allowed_hosts: ['public.example.com', 'optional.example.com'],
          },
        },
        created_at: '',
        updated_at: '',
      },
      recommendedHosts: [],
      mcpServers: [
        {
          type: 'streamable_http',
          name: 'GitHub',
          url: 'https://api.github.com/mcp',
          auth_requirement: 'required',
        },
        {
          type: 'streamable_http',
          name: 'Linear',
          url: 'https://mcp.linear.app/sse',
          auth_requirement: 'required',
        },
        {
          type: 'sse',
          name: 'Public',
          url: 'https://public.example.org/sse',
          auth_requirement: 'none',
        },
      ],
      credentialGroupMembers: [{ mcp_server_url: 'https://api.github.com/mcp' }],
    })

    expect(result.externalTools).toBe('not_authorized')
    expect(result.needsHardening).toBe(true)
  })

  it('uses the actual Agent MCP config when recommendations are unavailable', () => {
    const result = deriveQuickstartLaunchAssurance({
      hasRuntime: true,
      hasModelConnection: true,
      environment: null,
      recommendedHosts: [],
      mcpServers: [
        {
          type: 'streamable_http',
          name: 'Required API',
          url: 'https://required.example.com/mcp',
          auth_requirement: 'required',
        },
      ],
      credentialGroupMembers: [],
    })

    expect(result.externalTools).toBe('not_authorized')
  })

  it('does not block local, public, or optional-anonymous MCP servers', () => {
    const result = deriveQuickstartLaunchAssurance({
      hasRuntime: true,
      hasModelConnection: true,
      environment: {
        id: 'env_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111',
        name: 'locked-down',
        config: {
          networking: {
            type: 'limited',
            allowed_hosts: ['public.example.com', 'optional.example.com'],
          },
        },
        created_at: '',
        updated_at: '',
      },
      recommendedHosts: [],
      mcpServers: [
        { type: 'local_stdio', name: 'local', command: 'node', args: [], env: {} },
        {
          type: 'sse',
          name: 'public',
          url: 'https://public.example.com/sse',
          auth_requirement: 'none',
        },
        {
          type: 'streamable_http',
          name: 'optional',
          url: 'https://optional.example.com/mcp',
          auth_requirement: 'optional',
        },
      ],
      credentialGroupMembers: [],
    })

    expect(result.externalTools).toBe('ready')
    expect(result.needsHardening).toBe(false)
  })

  it('requires actual remote MCP hosts when recommendations are unavailable', () => {
    const result = deriveQuickstartLaunchAssurance({
      hasRuntime: true,
      hasModelConnection: true,
      environment: {
        id: 'env_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111',
        name: 'locked-down',
        config: { networking: { type: 'limited', allowed_hosts: [] } },
        created_at: '',
        updated_at: '',
      },
      recommendedHosts: [],
      mcpServers: [
        {
          type: 'streamable_http',
          name: 'Required API',
          url: 'https://required.example.com/mcp',
          auth_requirement: 'required',
        },
      ],
      credentialGroupMembers: [{ mcp_server_url: 'https://required.example.com/mcp' }],
    })

    expect(result.environment).toBe('recommended')
    expect(result.externalTools).toBe('ready')
    expect(result.needsHardening).toBe(true)
  })

  it('preserves internal MCP hosts when verifying the environment allowlist', () => {
    const result = deriveQuickstartLaunchAssurance({
      hasRuntime: true,
      hasModelConnection: true,
      environment: {
        id: 'env_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111',
        name: 'internal',
        config: { networking: { type: 'limited', allowed_hosts: ['localhost'] } },
        created_at: '',
        updated_at: '',
      },
      recommendedHosts: [],
      mcpServers: [
        {
          type: 'streamable_http',
          name: 'Local gateway',
          url: 'http://localhost:8080/mcp',
          auth_requirement: 'optional',
        },
      ],
      credentialGroupMembers: [],
    })

    expect(result.requiredHosts).toEqual(['localhost'])
    expect(result.environment).toBe('enforced')
  })

  it('blocks ambiguous MCP credential coverage', () => {
    const result = deriveQuickstartLaunchAssurance({
      hasRuntime: true,
      hasModelConnection: true,
      environment: null,
      recommendedHosts: [],
      mcpServers: [
        {
          type: 'streamable_http',
          name: 'Optional API',
          url: 'https://optional.example.com/mcp',
          auth_requirement: 'optional',
        },
      ],
      credentialGroupMembers: [
        { mcp_server_url: 'https://optional.example.com/mcp' },
        { mcp_server_url: 'https://optional.example.com/mcp/' },
      ],
    })

    expect(result.externalTools).toBe('not_authorized')
  })
})
