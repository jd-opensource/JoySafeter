import { describe, it, expect, vi, beforeEach } from 'vitest'
import { graphDataAdapter } from '../graphDataAdapter'
import { agentVersionService } from '@/services/agentVersionService'

vi.mock('@/services/agentVersionService')

describe('graphDataAdapter', () => {
  const mockVersion = {
    id: 'v1',
    definition_payload: {
      nodes: [{ id: 'n1' }],
      edges: [{ id: 'e1' }],
      viewport: { x: 0, y: 0, zoom: 1 },
      graphStateFields: [],
      fallbackNodeId: null,
    },
  }

  beforeEach(() => vi.clearAllMocks())

  it('load returns definition_payload as GraphState', async () => {
    vi.mocked(agentVersionService.get).mockResolvedValue(mockVersion as any)
    const state = await graphDataAdapter.load('a1', 'v1', 'w1')
    expect(agentVersionService.get).toHaveBeenCalledWith('a1', 'v1', 'w1')
    expect(state.nodes).toEqual([{ id: 'n1' }])
    expect(state.edges).toEqual([{ id: 'e1' }])
  })

  it('save calls agentVersionService.update with definition_payload', async () => {
    vi.mocked(agentVersionService.update).mockResolvedValue(mockVersion as any)
    const graphState = { nodes: [{ id: 'n2' }], edges: [], viewport: { x: 0, y: 0, zoom: 1 } }
    await graphDataAdapter.save('a1', 'v1', 'w1', graphState as any)
    expect(agentVersionService.update).toHaveBeenCalledWith('a1', 'v1', 'w1', {
      definition_payload: graphState,
    })
  })

  it('createDraft calls agentVersionService.create', async () => {
    vi.mocked(agentVersionService.create).mockResolvedValue({ id: 'v2' } as any)
    const id = await graphDataAdapter.createDraft('a1', 'w1')
    expect(id).toBe('v2')
    expect(agentVersionService.create).toHaveBeenCalledWith('a1', 'w1', {
      definition_kind: 'graph',
      definition_payload: {},
    })
  })
})
