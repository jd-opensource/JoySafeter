import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchQuickstartRecommendation } from '@/lib/managed/quickstart-recommendation-client'
import { useManagedRequestScope } from '@/lib/managed/request-scope'

import {
  EMPTY_SECURITY_DEFAULTS,
  mapEngineDefaults,
  mapSecurityDefaults,
  useQuickstartEngineDefaults,
  useQuickstartSecurityDefaults,
} from './use-quickstart-recommendation'

vi.mock('@/lib/managed/quickstart-recommendation-client', () => ({
  fetchQuickstartRecommendation: vi.fn(),
}))

vi.mock('@/lib/managed/request-scope', () => ({
  hasManagedRequestScope: (scope: { orgId: string | null; projectId: string | null }) =>
    Boolean(scope.orgId && scope.projectId),
  useManagedRequestScope: vi.fn(),
}))

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return createElement(QueryClientProvider, { client: queryClient }, children)
}

beforeEach(() => {
  vi.mocked(useManagedRequestScope).mockReturnValue({
    orgId: 'org-a' as never,
    projectId: 'project-a' as never,
    key: 'org-a:project-a',
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('mapEngineDefaults', () => {
  it('uses the backend recommendation as the single ranking authority', () => {
    expect(
      mapEngineDefaults({
        phase: 'understand',
        engine: {
          recommended_engine_id: 'codex',
          options: [
            { engine_id: 'codex', readiness: 'ready', compatible_connection_count: 2 },
            { engine_id: 'native', readiness: 'setup_required', compatible_connection_count: 0 },
          ],
        },
      }),
    ).toEqual([
      {
        engineId: 'codex',
        readiness: 'ready',
        compatibleConnectionCount: 2,
        recommended: true,
      },
      {
        engineId: 'native',
        readiness: 'setup_required',
        compatibleConnectionCount: 0,
        recommended: false,
      },
    ])
  })
})

describe('mapSecurityDefaults', () => {
  it('maps a secure recommendation with hosts and external tools into UI defaults', () => {
    const result = mapSecurityDefaults({
      phase: 'secure',
      environment: {
        allowed_hosts: ['github.com', 'api.github.com'],
        host_reason: 'knownServices',
      },
      credential_group: {
        mcp_servers: [
          {
            name: 'Acme MCP',
            url: 'https://mcp.acme.io/sse',
            auth_requirement: 'required',
          },
        ],
        external_tools_reason: 'mcpServers',
      },
    })
    expect(result).toEqual({
      recommendedHosts: ['github.com', 'api.github.com'],
      recommendedMcpServers: [
        {
          name: 'Acme MCP',
          url: 'https://mcp.acme.io/sse',
          authRequirement: 'required',
        },
      ],
      hostReason: 'knownServices',
      externalToolsRecommended: true,
      externalToolsReason: 'mcpServers',
    })
  })

  it('reports no external tools when the backend omits the credential group', () => {
    const result = mapSecurityDefaults({
      phase: 'secure',
      environment: {
        allowed_hosts: [],
        host_reason: 'none',
      },
      credential_group: null,
    })
    expect(result.externalToolsRecommended).toBe(false)
    expect(result.externalToolsReason).toBe('none')
    expect(result.recommendedMcpServers).toEqual([])
    expect(result.recommendedHosts).toEqual([])
  })

  it('returns empty defaults for a non-secure recommendation', () => {
    const result = mapSecurityDefaults({
      phase: 'understand',
      engine: { recommended_engine_id: 'codex', options: [] },
    })
    expect(result).toEqual(EMPTY_SECURITY_DEFAULTS)
  })

  it('returns empty defaults for undefined (loading/error)', () => {
    expect(mapSecurityDefaults(undefined)).toEqual(EMPTY_SECURITY_DEFAULTS)
  })
})

describe('recommendation query prerequisites', () => {
  it('keeps understand idle and retry inert without managed scope', async () => {
    vi.mocked(useManagedRequestScope).mockReturnValue({ orgId: null, projectId: null, key: ':' })

    const { result } = renderHook(
      () => useQuickstartEngineDefaults({ intent: 'Build an agent', enabled: true }),
      { wrapper },
    )

    expect(result.current.status).toBe('idle')
    act(() => result.current.retry())
    await Promise.resolve()
    expect(fetchQuickstartRecommendation).not.toHaveBeenCalled()
  })

  it('keeps secure idle and retry inert without intent', async () => {
    const { result } = renderHook(
      () => useQuickstartSecurityDefaults({ intent: '   ', enabled: true }),
      { wrapper },
    )

    expect(result.current.status).toBe('idle')
    act(() => result.current.retry())
    await Promise.resolve()
    expect(fetchQuickstartRecommendation).not.toHaveBeenCalled()
  })

  it('queries secure recommendations from an Agent draft without intent text', async () => {
    vi.mocked(fetchQuickstartRecommendation).mockResolvedValueOnce({
      phase: 'secure',
      environment: { allowed_hosts: [], host_reason: 'none' },
      credential_group: null,
    })

    const agentConfig = { name: 'Imported Agent', mcp_servers: [] }
    const { result } = renderHook(
      () => useQuickstartSecurityDefaults({ intent: '   ', agentConfig, enabled: true }),
      { wrapper },
    )

    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(fetchQuickstartRecommendation).toHaveBeenCalledWith(
      { phase: 'secure', intent: '   ', agent_context: agentConfig },
      expect.objectContaining({ key: 'org-a:project-a' }),
    )
  })

  it('reports loading only while an enabled recommendation is pending', async () => {
    let resolveRecommendation!: (value: {
      phase: 'understand'
      engine: {
        recommended_engine_id: string
        options: Array<{
          engine_id: string
          readiness: 'ready'
          compatible_connection_count: number
        }>
      }
    }) => void
    vi.mocked(fetchQuickstartRecommendation).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRecommendation = resolve
      }),
    )

    const { result } = renderHook(
      () => useQuickstartEngineDefaults({ intent: 'Build an agent', enabled: true }),
      { wrapper },
    )

    expect(result.current.status).toBe('loading')
    resolveRecommendation({
      phase: 'understand',
      engine: {
        recommended_engine_id: 'codex',
        options: [{ engine_id: 'codex', readiness: 'ready', compatible_connection_count: 1 }],
      },
    })
    await waitFor(() => expect(result.current.status).toBe('ready'))
  })
})
