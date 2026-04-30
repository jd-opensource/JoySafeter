import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { SaveManager } from '../saveManager'
import { visualDefinitionAdapter } from '../../services/visualDefinitionAdapter'

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
  let saveSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    Object.defineProperty(navigator, 'onLine', {
      configurable: true,
      value: true,
    })
    saveSpy = vi.spyOn(visualDefinitionAdapter, 'save')
    saveSpy.mockResolvedValue({ versionId: 'version-1' })
    onSaveSuccess = vi.fn()
    onSaveError = vi.fn()
    getState = vi.fn().mockReturnValue(validState())
    manager = new SaveManager(getState, { onSaveSuccess, onSaveError })
  })

  afterEach(() => {
    saveSpy.mockRestore()
  })

  it('calls visualDefinitionAdapter.save with correct payload', async () => {
    await manager.save('manual')
    expect(saveSpy).toHaveBeenCalledOnce()
    const [agentId, versionId, workspaceId, payload] = saveSpy.mock.calls[0]
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
    expect(saveSpy).not.toHaveBeenCalled()
  })

  it('calls onSaveError when save throws', async () => {
    saveSpy.mockRejectedValueOnce(new Error('network error'))
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
