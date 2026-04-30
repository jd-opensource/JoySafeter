import { describe, it, expect, vi, beforeEach } from 'vitest'
import { visualDefinitionAdapter } from '../visualDefinitionAdapter'
import { agentVersionService } from '@/services/agentVersionService'

vi.mock('@/lib/api-client', () => ({
  API_BASE: 'https://api.example.test',
}))

vi.mock('@/services/agentVersionService', () => ({
  agentVersionService: {
    get: vi.fn(),
    update: vi.fn(),
    create: vi.fn(),
  },
}))

const originalFetch = globalThis.fetch

describe('visualDefinitionAdapter', () => {
  const mockVersion = {
    id: 'version-1',
    definition_kind: 'graph',
    status: 'draft',
    definition_payload: {
      graphId: 'graph-1',
      graphName: 'Graph One',
      nodes: [{ id: 'node-1' }],
      edges: [{ id: 'edge-1', source: 'node-1', target: 'node-2' }],
      viewport: { x: 10, y: 20, zoom: 1.5 },
      graphStateFields: [{ name: 'count', type: 'int' }],
      fallbackNodeId: 'node-1',
    },
  }

  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(globalThis, 'fetch', {
      configurable: true,
      writable: true,
      value: originalFetch,
    })
  })

  it('loads definition_payload graph state and annotates ownership ids', async () => {
    ;(agentVersionService.get as ReturnType<typeof vi.fn>).mockResolvedValue(mockVersion as any)

    const state = await visualDefinitionAdapter.load('agent-1', 'version-1', 'workspace-1')

    expect(agentVersionService.get).toHaveBeenCalledWith('agent-1', 'version-1', 'workspace-1')
    expect(state).toEqual({
      graphId: 'graph-1',
      graphName: 'Graph One',
      nodes: [{ id: 'node-1' }],
      edges: [{ id: 'edge-1', source: 'node-1', target: 'node-2' }],
      viewport: { x: 10, y: 20, zoom: 1.5 },
      graphStateFields: [{ name: 'count', type: 'int' }],
      fallbackNodeId: 'node-1',
      agentId: 'agent-1',
      versionId: 'version-1',
      workspaceId: 'workspace-1',
    })
  })

  it('saves graph state as definition_payload and returns the updated version id', async () => {
    ;(agentVersionService.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...mockVersion,
      definition_payload: {
        ...mockVersion.definition_payload,
        variables: { existing: true },
        context: { user_id: { type: 'string' } },
        graph_mode: 'custom',
        code_content: 'print("hello")',
        node_secrets: { 'node-1': ['API_KEY'] },
        future_payload_key: { keep: 'me' },
      },
    } as any)
    ;(agentVersionService.update as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'version-2',
    } as any)
    const graphState = {
      nodes: [{ id: 'node-2' }],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      graphStateFields: [],
      fallbackNodeId: null,
    }

    const result = await visualDefinitionAdapter.save(
      'agent-1',
      'version-1',
      'workspace-1',
      graphState as any,
    )

    expect(agentVersionService.update).toHaveBeenCalledWith('agent-1', 'version-1', 'workspace-1', {
      definition_payload: {
        graphId: 'graph-1',
        graphName: 'Graph One',
        nodes: [{ id: 'node-2' }],
        edges: [],
        viewport: { x: 0, y: 0, zoom: 1 },
        graphStateFields: [],
        fallbackNodeId: null,
        variables: { existing: true },
        context: { user_id: { type: 'string' } },
        graph_mode: 'custom',
        code_content: 'print("hello")',
        node_secrets: { 'node-1': ['API_KEY'] },
        future_payload_key: { keep: 'me' },
      },
    })
    expect(result).toEqual({ versionId: 'version-2' })
  })

  it('loads version graph state with metadata and raw payload through the adapter boundary', async () => {
    ;(agentVersionService.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...mockVersion,
      definition_kind: 'code',
      status: 'frozen',
      definition_payload: {
        ...mockVersion.definition_payload,
        code_content: 'return 1',
      },
    } as any)

    const result = await visualDefinitionAdapter.loadVersionGraphState(
      'agent-1',
      'version-1',
      'workspace-1',
    )

    expect(agentVersionService.get).toHaveBeenCalledWith('agent-1', 'version-1', 'workspace-1')
    expect(result).toEqual({
      graphState: {
        graphId: 'graph-1',
        graphName: 'Graph One',
        nodes: [{ id: 'node-1' }],
        edges: [{ id: 'edge-1', source: 'node-1', target: 'node-2' }],
        viewport: { x: 10, y: 20, zoom: 1.5 },
        graphStateFields: [{ name: 'count', type: 'int' }],
        fallbackNodeId: 'node-1',
        agentId: 'agent-1',
        versionId: 'version-1',
        workspaceId: 'workspace-1',
      },
      definitionKind: 'code',
      versionStatus: 'frozen',
      rawPayload: {
        ...mockVersion.definition_payload,
        code_content: 'return 1',
      },
    })
  })

  it('merges cached definition payload into beacon saves', async () => {
    ;(agentVersionService.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...mockVersion,
      definition_payload: {
        ...mockVersion.definition_payload,
        graph_mode: 'custom',
        code_content: 'print("hello")',
        context: { user_id: { type: 'string' } },
        node_secrets: { 'node-1': ['API_KEY'] },
        future_payload_key: { keep: 'me' },
      },
    } as any)
    const fetchMock = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(globalThis, 'fetch', {
      configurable: true,
      writable: true,
      value: fetchMock,
    })

    await visualDefinitionAdapter.loadVersionGraphState('agent-1', 'version-1', 'workspace-1')
    visualDefinitionAdapter.sendBeaconSave('agent-1', 'version-1', 'workspace-1', {
      nodes: [{ id: 'node-2' }],
      edges: [{ id: 'edge-2', source: 'node-2', target: 'node-3' }],
      viewport: { x: 0, y: 0, zoom: 1 },
    })

    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example.test/agents/agent-1/versions/version-1?workspace_id=workspace-1',
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          definition_payload: {
            graphId: 'graph-1',
            graphName: 'Graph One',
            nodes: [{ id: 'node-2' }],
            edges: [{ id: 'edge-2', source: 'node-2', target: 'node-3' }],
            viewport: { x: 0, y: 0, zoom: 1 },
            graphStateFields: [{ name: 'count', type: 'int' }],
            fallbackNodeId: 'node-1',
            graph_mode: 'custom',
            code_content: 'print("hello")',
            context: { user_id: { type: 'string' } },
            node_secrets: { 'node-1': ['API_KEY'] },
            future_payload_key: { keep: 'me' },
          },
        }),
        keepalive: true,
      },
    )
  })

  it('preserves merged payload cache when save forks to a new version id', async () => {
    ;(agentVersionService.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...mockVersion,
      definition_payload: {
        ...mockVersion.definition_payload,
        graph_mode: 'custom',
        code_content: 'print("hello")',
        context: { user_id: { type: 'string' } },
        node_secrets: { 'node-1': ['API_KEY'] },
        future_payload_key: { keep: 'me' },
      },
    } as any)
    ;(agentVersionService.update as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'version-fork',
    } as any)
    const fetchMock = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(globalThis, 'fetch', {
      configurable: true,
      writable: true,
      value: fetchMock,
    })

    await visualDefinitionAdapter.save('agent-1', 'version-1', 'workspace-1', {
      nodes: [{ id: 'node-2' }] as any,
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
    })

    visualDefinitionAdapter.sendBeaconSave('agent-1', 'version-fork', 'workspace-1', {
      nodes: [{ id: 'node-3' }],
      edges: [],
      viewport: { x: 5, y: 6, zoom: 2 },
    })

    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example.test/agents/agent-1/versions/version-fork?workspace_id=workspace-1',
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          definition_payload: {
            graphId: 'graph-1',
            graphName: 'Graph One',
            nodes: [{ id: 'node-3' }],
            edges: [],
            viewport: { x: 5, y: 6, zoom: 2 },
            graphStateFields: [{ name: 'count', type: 'int' }],
            fallbackNodeId: 'node-1',
            graph_mode: 'custom',
            code_content: 'print("hello")',
            context: { user_id: { type: 'string' } },
            node_secrets: { 'node-1': ['API_KEY'] },
            future_payload_key: { keep: 'me' },
          },
        }),
        keepalive: true,
      },
    )
  })

  it('maps legacy snake_case visual fields into graph state fields', async () => {
    ;(agentVersionService.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...mockVersion,
      definition_payload: {
        nodes: [],
        edges: [],
        state_fields: [{ name: 'legacy_count', type: 'int' }],
        fallback_node_id: 'legacy-node',
      },
    } as any)

    const result = await visualDefinitionAdapter.load('agent-1', 'version-1', 'workspace-1')

    expect(result.graphStateFields).toEqual([{ name: 'legacy_count', type: 'int' }])
    expect(result.fallbackNodeId).toBe('legacy-node')
  })
})
