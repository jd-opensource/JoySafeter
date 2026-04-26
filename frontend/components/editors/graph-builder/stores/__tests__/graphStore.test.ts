import { describe, it, expect, beforeEach } from 'vitest'
import { useGraphStore } from '../graphStore'

describe('graphStore', () => {
  beforeEach(() => {
    useGraphStore.setState(useGraphStore.getInitialState())
  })

  it('initializes with empty nodes and edges', () => {
    const state = useGraphStore.getState()
    expect(state.nodes).toEqual([])
    expect(state.edges).toEqual([])
  })

  it('tracks selectedNodeId', () => {
    useGraphStore.getState().selectNode('node-1')
    expect(useGraphStore.getState().selectedNodeId).toBe('node-1')
  })

  it('tracks selectedEdgeId', () => {
    useGraphStore.getState().selectEdge('edge-1')
    expect(useGraphStore.getState().selectedEdgeId).toBe('edge-1')
  })

  it('clearSelection clears both', () => {
    useGraphStore.getState().selectNode('node-1')
    useGraphStore.getState().selectEdge('edge-1')
    useGraphStore.getState().clearSelection()
    expect(useGraphStore.getState().selectedNodeId).toBeNull()
    expect(useGraphStore.getState().selectedEdgeId).toBeNull()
  })

  it('stores identity fields', () => {
    useGraphStore.setState({ agentId: 'a-1', versionId: 'v-1', workspaceId: 'ws-1' })
    const s = useGraphStore.getState()
    expect(s.agentId).toBe('a-1')
  })
})
