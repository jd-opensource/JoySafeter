import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useGraphStore } from '../graphStore'
import { useSaveStore } from '../saveStore'
import { computeGraphStateHash } from '@/lib/utils/graphStateHash'

vi.mock('../../services/agentService', () => ({
  agentService: {
    saveGraphState: vi.fn().mockResolvedValue({}),
    loadGraphState: vi.fn().mockResolvedValue({ nodes: [], edges: [] }),
    getInitialGraph: vi.fn().mockResolvedValue({ nodes: [], edges: [] }),
    setCachedGraphId: vi.fn(),
    setCachedGraphName: vi.fn(),
    clearCachedGraphId: vi.fn(),
    clearCachedGraphName: vi.fn(),
    listGraphs: vi.fn().mockResolvedValue([]),
    saveGraph: vi.fn().mockResolvedValue({ graphId: 'g1' }),
  },
}))

vi.mock('@/stores/sidebar/store', () => ({
  useSidebarStore: { getState: () => ({ isCollapsed: false, sidebarWidth: 280 }) },
}))

const SEED_NODE = { id: 'n1', type: 'custom', position: { x: 0, y: 0 }, data: {} } as any
const SEED_EDGE = { id: 'e1', source: 'n1', target: 'n2' } as any

function resetStores() {
  const nodes = [SEED_NODE]
  const edges = [SEED_EDGE]
  const hash = computeGraphStateHash(nodes, edges, [], null)
  useGraphStore.setState({
    nodes,
    edges,
    graphId: 'test-graph-id',
    graphName: 'Test',
    graphStateFields: [],
    fallbackNodeId: null,
    past: [],
    future: [],
    isInitializing: false,
  })
  useSaveStore.setState({
    lastSavedStateHash: hash,
    hasPendingChanges: false,
    saveRetryCount: 0,
    lastSaveError: null,
  })
}

describe('onNodesChange — dirty state filtering', () => {
  beforeEach(resetStores)

  it('does NOT set hasPendingChanges for dimensions change', () => {
    useGraphStore
      .getState()
      .onNodesChange([
        { type: 'dimensions', id: 'n1', dimensions: { width: 100, height: 50 }, resizing: false },
      ])
    expect(useSaveStore.getState().hasPendingChanges).toBe(false)
  })

  it('does NOT set hasPendingChanges for select change', () => {
    useGraphStore.getState().onNodesChange([{ type: 'select', id: 'n1', selected: true }])
    expect(useSaveStore.getState().hasPendingChanges).toBe(false)
  })

  it('DOES set hasPendingChanges for position change', () => {
    useGraphStore
      .getState()
      .onNodesChange([{ type: 'position', id: 'n1', position: { x: 10, y: 20 } }])
    expect(useSaveStore.getState().hasPendingChanges).toBe(true)
  })

  it('DOES set hasPendingChanges for remove change', () => {
    useGraphStore.getState().onNodesChange([{ type: 'remove', id: 'n1' }])
    expect(useSaveStore.getState().hasPendingChanges).toBe(true)
  })
})

describe('onEdgesChange — dirty state filtering', () => {
  beforeEach(resetStores)

  it('does NOT set hasPendingChanges for select change', () => {
    useGraphStore.getState().onEdgesChange([{ type: 'select', id: 'e1', selected: true }])
    expect(useSaveStore.getState().hasPendingChanges).toBe(false)
  })

  it('DOES set hasPendingChanges for remove change', () => {
    useGraphStore.getState().onEdgesChange([{ type: 'remove', id: 'e1' }])
    expect(useSaveStore.getState().hasPendingChanges).toBe(true)
  })
})

describe('hasPendingChanges — derived from hash', () => {
  it('is false when currentHash equals lastSavedStateHash', () => {
    const nodes = [{ id: 'n1', type: 'custom', position: { x: 0, y: 0 }, data: {} }] as any
    const hash = computeGraphStateHash(nodes, [], [], null)
    useSaveStore.setState({ lastSavedStateHash: hash })
    useGraphStore.setState({ nodes, edges: [], graphStateFields: [], fallbackNodeId: null })
    expect(useSaveStore.getState().hasPendingChanges).toBe(false)
  })

  it('is true when nodes differ from lastSavedStateHash', () => {
    const nodes = [{ id: 'n1', type: 'custom', position: { x: 0, y: 0 }, data: {} }] as any
    const hash = computeGraphStateHash([], [], [], null)
    useSaveStore.setState({ lastSavedStateHash: hash })
    useGraphStore.setState({ nodes, edges: [], graphStateFields: [], fallbackNodeId: null })
    expect(useSaveStore.getState().hasPendingChanges).toBe(true)
  })

  it('is true when lastSavedStateHash is null (never saved)', () => {
    useSaveStore.setState({ lastSavedStateHash: null })
    useGraphStore.setState({ nodes: [SEED_NODE], edges: [], graphStateFields: [], fallbackNodeId: null })
    expect(useSaveStore.getState().hasPendingChanges).toBe(true)
  })

  it('is false when lastSavedStateHash is null AND nodes/edges are empty (new unsaved graph)', () => {
    useSaveStore.setState({ lastSavedStateHash: null })
    useGraphStore.setState({ nodes: [], edges: [], graphStateFields: [], fallbackNodeId: null, graphId: null })
    expect(useSaveStore.getState().hasPendingChanges).toBe(false)
  })
})
