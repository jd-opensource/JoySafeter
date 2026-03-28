import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SaveManager } from '../saveManager'

const mockSaveGraphState = vi.fn().mockResolvedValue({})

vi.mock('../../services/agentService', () => ({
  agentService: { saveGraphState: (...args: any[]) => mockSaveGraphState(...args) },
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

describe('SaveManager (simplified)', () => {
  let onSaveSuccess: ReturnType<typeof vi.fn>
  let onSaveError: ReturnType<typeof vi.fn>
  let getState: ReturnType<typeof vi.fn>
  let manager: SaveManager

  beforeEach(() => {
    mockSaveGraphState.mockClear()
    onSaveSuccess = vi.fn()
    onSaveError = vi.fn()
    getState = vi.fn().mockReturnValue(baseState())
    manager = new SaveManager(getState, { onSaveSuccess, onSaveError })
  })

  it('calls agentService.saveGraphState with correct payload', async () => {
    await manager.save('manual')
    expect(mockSaveGraphState).toHaveBeenCalledOnce()
    const call = mockSaveGraphState.mock.calls[0][0]
    expect(call.graphId).toBe('graph-1')
    expect(call.nodes).toEqual([])
  })

  it('calls onSaveSuccess with the saved graphId', async () => {
    await manager.save('manual')
    expect(onSaveSuccess).toHaveBeenCalledWith(expect.any(String), 'graph-1')
  })

  it('does NOT save when graphId is null', async () => {
    getState.mockReturnValue({ ...baseState(), graphId: null })
    await manager.save('manual')
    expect(mockSaveGraphState).not.toHaveBeenCalled()
  })

  it('calls onSaveError when save throws', async () => {
    mockSaveGraphState.mockRejectedValueOnce(new Error('network error'))
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
