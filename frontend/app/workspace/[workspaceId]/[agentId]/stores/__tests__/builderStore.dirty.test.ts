import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useBuilderStore } from '../builderStore'
import { computeGraphStateHash } from '@/lib/utils/graphStateHash'

// SaveManager makes real API calls — mock the whole module
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

function resetStore() {
  const nodes = [SEED_NODE]
  const edges = [SEED_EDGE]
  useBuilderStore.setState({
    nodes,
    edges,
    graphId: 'test-graph-id',
    graphName: 'Test',
    lastSavedStateHash: computeGraphStateHash(nodes, edges, [], null),
    graphStateFields: [],
    fallbackNodeId: null,
    past: [],
    future: [],
    isInitializing: false,
  })
}

describe('onNodesChange — dirty state filtering', () => {
  beforeEach(resetStore)

  it('does NOT set hasPendingChanges for dimensions change', () => {
    useBuilderStore.getState().onNodesChange([
      { type: 'dimensions', id: 'n1', dimensions: { width: 100, height: 50 }, resizing: false },
    ])
    expect(useBuilderStore.getState().hasPendingChanges).toBe(false)
  })

  it('does NOT set hasPendingChanges for select change', () => {
    useBuilderStore.getState().onNodesChange([
      { type: 'select', id: 'n1', selected: true },
    ])
    expect(useBuilderStore.getState().hasPendingChanges).toBe(false)
  })

  it('DOES set hasPendingChanges for position change', () => {
    useBuilderStore.getState().onNodesChange([
      { type: 'position', id: 'n1', position: { x: 10, y: 20 } },
    ])
    expect(useBuilderStore.getState().hasPendingChanges).toBe(true)
  })

  it('DOES set hasPendingChanges for remove change', () => {
    useBuilderStore.getState().onNodesChange([
      { type: 'remove', id: 'n1' },
    ])
    expect(useBuilderStore.getState().hasPendingChanges).toBe(true)
  })
})

describe('onEdgesChange — dirty state filtering', () => {
  beforeEach(resetStore)

  it('does NOT set hasPendingChanges for select change', () => {
    useBuilderStore.getState().onEdgesChange([
      { type: 'select', id: 'e1', selected: true },
    ])
    expect(useBuilderStore.getState().hasPendingChanges).toBe(false)
  })

  it('DOES set hasPendingChanges for remove change', () => {
    useBuilderStore.getState().onEdgesChange([
      { type: 'remove', id: 'e1' },
    ])
    expect(useBuilderStore.getState().hasPendingChanges).toBe(true)
  })
})

describe('hasPendingChanges — derived from hash', () => {
  it('is false when currentHash equals lastSavedStateHash', () => {
    const nodes = [{ id: 'n1', type: 'custom', position: { x: 0, y: 0 }, data: {} }] as any
    const hash = computeGraphStateHash(nodes, [], [], null)
    useBuilderStore.setState({ nodes, edges: [], graphStateFields: [], fallbackNodeId: null, lastSavedStateHash: hash })
    expect(useBuilderStore.getState().hasPendingChanges).toBe(false)
  })

  it('is true when nodes differ from lastSavedStateHash', () => {
    const nodes = [{ id: 'n1', type: 'custom', position: { x: 0, y: 0 }, data: {} }] as any
    const hash = computeGraphStateHash([], [], [], null) // hash of empty state
    useBuilderStore.setState({ nodes, edges: [], graphStateFields: [], fallbackNodeId: null, lastSavedStateHash: hash })
    expect(useBuilderStore.getState().hasPendingChanges).toBe(true)
  })

  it('is true when lastSavedStateHash is null (never saved)', () => {
    useBuilderStore.setState({ nodes: [], edges: [], graphStateFields: [], fallbackNodeId: null, lastSavedStateHash: null })
    expect(useBuilderStore.getState().hasPendingChanges).toBe(true)
  })

  it('is false when lastSavedStateHash is null AND nodes/edges are empty (new unsaved graph)', () => {
    // New empty graph: no graphId, no hash, no content — not dirty
    useBuilderStore.setState({ nodes: [], edges: [], graphStateFields: [], fallbackNodeId: null, lastSavedStateHash: null, graphId: null })
    expect(useBuilderStore.getState().hasPendingChanges).toBe(false)
  })
})
