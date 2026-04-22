import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SaveManager } from '../saveManager'

const mockSaveGraphState = vi.fn().mockResolvedValue({})
const mockGraphDataAdapterSave = vi.fn().mockResolvedValue(undefined)

vi.mock('../../services/agentService', () => ({
  agentService: { saveGraphState: (...args: any[]) => mockSaveGraphState(...args) },
}))

vi.mock('../../services/graphDataAdapter', () => ({
  graphDataAdapter: { save: (...args: any[]) => mockGraphDataAdapterSave(...args) },
}))

const baseState = () => ({
  graphId: 'graph-1',
  graphName: 'Test',
  nodes: [],
  edges: [],
  viewport: { x: 0, y: 0, zoom: 1 },
  graphStateFields: [],
  fallbackNodeId: null,
})

const newPathState = () => ({
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

describe('SaveManager (simplified)', () => {
  let onSaveSuccess: ReturnType<typeof vi.fn>
  let onSaveError: ReturnType<typeof vi.fn>
  let getState: ReturnType<typeof vi.fn>
  let manager: SaveManager

  beforeEach(() => {
    mockSaveGraphState.mockClear()
    mockGraphDataAdapterSave.mockClear()
    onSaveSuccess = vi.fn()
    onSaveError = vi.fn()
    getState = vi.fn().mockReturnValue(baseState())
    manager = new SaveManager(getState, { onSaveSuccess, onSaveError })
  })

  // ─── Legacy graphId path ────────────────────────────────────────────────────

  it('calls agentService.saveGraphState with correct payload (legacy path)', async () => {
    await manager.save('manual')
    expect(mockSaveGraphState).toHaveBeenCalledOnce()
    const call = mockSaveGraphState.mock.calls[0][0]
    expect(call.graphId).toBe('graph-1')
    expect(call.nodes).toEqual([])
  })

  it('does NOT call graphDataAdapter.save when only graphId is present', async () => {
    await manager.save('manual')
    expect(mockGraphDataAdapterSave).not.toHaveBeenCalled()
  })

  it('calls onSaveSuccess with the saved graphId (legacy path)', async () => {
    await manager.save('manual')
    expect(onSaveSuccess).toHaveBeenCalledWith(expect.any(String), 'graph-1')
  })

  it('does NOT save when graphId is null and no agentId/versionId', async () => {
    getState.mockReturnValue({ ...baseState(), graphId: null })
    await manager.save('manual')
    expect(mockSaveGraphState).not.toHaveBeenCalled()
    expect(mockGraphDataAdapterSave).not.toHaveBeenCalled()
  })

  it('calls onSaveError when legacy save throws', async () => {
    mockSaveGraphState.mockRejectedValueOnce(new Error('network error'))
    await manager.save('manual')
    expect(onSaveError).toHaveBeenCalledWith('network error')
  })

  // ─── New agentId/versionId/workspaceId path ─────────────────────────────────

  it('calls graphDataAdapter.save with correct payload (new path)', async () => {
    getState.mockReturnValue(newPathState())
    await manager.save('manual')
    expect(mockGraphDataAdapterSave).toHaveBeenCalledOnce()
    const [agentId, versionId, workspaceId, payload] = mockGraphDataAdapterSave.mock.calls[0]
    expect(agentId).toBe('agent-1')
    expect(versionId).toBe('version-1')
    expect(workspaceId).toBe('ws-1')
    expect(payload.nodes).toEqual([])
    expect(payload.edges).toEqual([])
  })

  it('does NOT call agentService.saveGraphState when new path is used', async () => {
    getState.mockReturnValue(newPathState())
    await manager.save('manual')
    expect(mockSaveGraphState).not.toHaveBeenCalled()
  })

  it('calls onSaveSuccess with agentId when new path is used', async () => {
    getState.mockReturnValue(newPathState())
    await manager.save('manual')
    expect(onSaveSuccess).toHaveBeenCalledWith(expect.any(String), 'agent-1')
  })

  it('calls onSaveError when new-path save throws', async () => {
    mockGraphDataAdapterSave.mockRejectedValueOnce(new Error('version error'))
    getState.mockReturnValue(newPathState())
    await manager.save('manual')
    expect(onSaveError).toHaveBeenCalledWith('version error')
  })

  // ─── Internal state invariants ───────────────────────────────────────────────

  it('does NOT have a setLastSavedHash method', () => {
    expect((manager as any).setLastSavedHash).toBeUndefined()
  })

  it('does NOT have a lastSavedHash field', () => {
    expect((manager as any).lastSavedHash).toBeUndefined()
  })
})
