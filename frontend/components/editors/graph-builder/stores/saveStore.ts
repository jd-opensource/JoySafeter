'use client'

import { create } from 'zustand'

import { computeGraphStateHash } from '@/lib/utils/graphStateHash'

import { SaveManager, type GraphState as SaveManagerGraphState } from '../utils/saveManager'
import { useGraphStore, setAutoSaveTrigger } from './graphStore'

interface SaveState {
  isSaving: boolean
  lastAutoSaveTime: number | null
  lastSavedStateHash: string | null
  hasPendingChanges: boolean
  saveRetryCount: number
  lastSaveError: string | null

  startAutoSave: () => void
  stopAutoSave: () => void
  saveNow: (reason?: string) => Promise<void>
  autoSave: () => Promise<void>
  triggerAutoSave: () => void
}

function getGraphSnapshot(): SaveManagerGraphState {
  const gs = useGraphStore.getState()
  return {
    agentId: gs.agentId,
    versionId: gs.versionId,
    workspaceId: gs.workspaceId,
    graphId: gs.graphId,
    graphName: gs.graphName,
    nodes: gs.nodes,
    edges: gs.edges,
    viewport: gs.rfInstance?.getViewport(),
    graphStateFields: gs.graphStateFields,
    fallbackNodeId: gs.fallbackNodeId,
  }
}

export const useSaveStore = create<SaveState>((set, get) => {
  const manager = new SaveManager(getGraphSnapshot, {
    onSaveSuccess: (hash, savedGraphId) => {
      const gs = useGraphStore.getState()
      if (savedGraphId && savedGraphId !== gs.graphId && savedGraphId !== gs.agentId) return
      set({
        isSaving: false,
        lastSavedStateHash: hash,
        lastAutoSaveTime: Date.now(),
        saveRetryCount: 0,
        lastSaveError: null,
      })
    },
    onSaveError: (error) => {
      set((s) => ({
        isSaving: false,
        saveRetryCount: s.saveRetryCount + 1,
        lastSaveError: error,
      }))
    },
  })

  return {
    isSaving: false,
    lastAutoSaveTime: null,
    lastSavedStateHash: null,
    hasPendingChanges: false,
    saveRetryCount: 0,
    lastSaveError: null,

    startAutoSave: () => {
      manager.save('auto')
    },

    stopAutoSave: () => {
      manager.stopAll()
    },

    saveNow: async (reason = 'manual') => {
      set({ isSaving: true })
      await manager.save(reason as 'manual' | 'auto' | 'debounce')
    },

    autoSave: async () => {
      await manager.save('auto')
    },

    triggerAutoSave: () => {
      const gs = useGraphStore.getState()
      const hasPath = !!(gs.agentId && gs.versionId && gs.workspaceId)
      if (!gs.graphId && !hasPath) return
      manager.debouncedSave()
    },
  }
})

setAutoSaveTrigger(() => {
  useSaveStore.getState().triggerAutoSave()
})

// Reactive hasPendingChanges: subscribe to graphStore and recompute on change
useGraphStore.subscribe((state, prev) => {
  if (
    state.nodes === prev.nodes &&
    state.edges === prev.edges &&
    state.graphStateFields === prev.graphStateFields &&
    state.fallbackNodeId === prev.fallbackNodeId
  ) {
    return
  }

  const { lastSavedStateHash } = useSaveStore.getState()
  const { nodes, edges, graphStateFields, fallbackNodeId, graphId } = state

  if (!graphId && nodes.length === 0 && edges.length === 0) {
    useSaveStore.setState({ hasPendingChanges: false })
    return
  }

  const currentHash = computeGraphStateHash(nodes, edges, graphStateFields, fallbackNodeId)
  const hasPendingChanges = lastSavedStateHash !== null
    ? currentHash !== lastSavedStateHash
    : nodes.length > 0 || edges.length > 0
  useSaveStore.setState({ hasPendingChanges })
})
const saveStoreInitialState = useSaveStore.getState()
;(useSaveStore as unknown as { getInitialState: () => SaveState }).getInitialState =
  () => saveStoreInitialState
