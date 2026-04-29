import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SaveManager } from '../saveManager'

const mockGraphDataAdapterSave = vi.fn().mockResolvedValue({ versionId: 'version-1' })

vi.mock('../../services/graphDataAdapter', () => ({
  graphDataAdapter: { save: (...args: any[]) => mockGraphDataAdapterSave(...args) },
}))

const validState = () => ({
  graphId: null,
  graphName: 'Test',
  agentId: 'agent-1',
  versionId: 'version-1',
  workspaceId: 'ws-1',
  nodes: [],
  edges: [],
  viewport: { x: 0, y: 0, zoom: 1 },
  graphStateFields: [],
  fallbackNodeId: null,
})

describe('SaveManager', () => {
  let onSaveSuccess: ReturnType<typeof vi.fn>
  let onSaveError: ReturnType<typeof vi.fn>
  let getState: ReturnType<typeof vi.fn>
  let manager: SaveManager

  beforeEach(() => {
    mockGraphDataAdapterSave.mockClear()
    onSaveSuccess = vi.fn()
    onSaveError = vi.fn()
    getState = vi.fn().mockReturnValue(validState())
    manager = new SaveManager(getState, { onSaveSuccess, onSaveError })
  })

  it('calls graphDataAdapter.save with correct payload', async () => {
    await manager.save('manual')
    expect(mockGraphDataAdapterSave).toHaveBeenCalledOnce()
    const [agentId, versionId, workspaceId, payload] = mockGraphDataAdapterSave.mock.calls[0]
    expect(agentId).toBe('agent-1')
    expect(versionId).toBe('version-1')
    expect(workspaceId).toBe('ws-1')
    expect(payload.nodes).toEqual([])
    expect(payload.edges).toEqual([])
  })

  it('calls onSaveSuccess with hash and agentId', async () => {
    await manager.save('manual')
    expect(onSaveSuccess).toHaveBeenCalledWith(expect.any(String), 'agent-1')
  })

  it('does NOT save when agentId/versionId/workspaceId are missing', async () => {
    getState.mockReturnValue({ ...validState(), agentId: null })
    await manager.save('manual')
    expect(mockGraphDataAdapterSave).not.toHaveBeenCalled()
  })

  it('calls onSaveError when save throws', async () => {
    mockGraphDataAdapterSave.mockRejectedValueOnce(new Error('network error'))
    await manager.save('manual')
    expect(onSaveError).toHaveBeenCalledWith('network error')
  })

  it('does NOT have a setLastSavedHash method', () => {
    expect((manager as any).setLastSavedHash).toBeUndefined()
  })

  it('does NOT have a lastSavedHash field', () => {
    expect((manager as any).lastSavedHash).toBeUndefined()
  })
})
