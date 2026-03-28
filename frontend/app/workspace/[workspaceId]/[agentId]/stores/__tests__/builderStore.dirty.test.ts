import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useBuilderStore } from '../builderStore'

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

function resetStore() {
  useBuilderStore.setState({
    nodes: [],
    edges: [],
    graphId: 'test-graph-id',
    graphName: 'Test',
    hasPendingChanges: false,
    lastSavedStateHash: null,
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
