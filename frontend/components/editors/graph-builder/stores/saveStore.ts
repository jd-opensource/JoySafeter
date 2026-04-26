'use client'

import { create } from 'zustand'

import { SaveManager, type GraphState as SaveManagerGraphState } from '../utils/saveManager'
import { useGraphStore } from './graphStore'

interface SaveState {
  isSaving: boolean
  lastAutoSaveTime: number | null
  deployedAt: string | null
  lastSavedStateHash: string | null
  hasPendingChanges: boolean
  saveRetryCount: number
  lastSaveError: string | null

  startAutoSave: () => void
  stopAutoSave: () => void
  saveNow: (reason?: string) => Promise<void>
  autoSave: () => Promise<void>
  setDeployedAt: (deployedAt: string | null) => void
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
    deployedAt: null,
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

    setDeployedAt: (deployedAt) => set({ deployedAt }),

    triggerAutoSave: () => {
      const gs = useGraphStore.getState()
      const hasPath = !!(gs.agentId && gs.versionId && gs.workspaceId)
      if (!gs.graphId && !hasPath) return
      manager.debouncedSave()
    },
  }
})

// Expose getInitialState for test resets
;(useSaveStore as unknown as { getInitialState: () => SaveState }).getInitialState = () => ({
  isSaving: false,
  lastAutoSaveTime: null,
  deployedAt: null,
  lastSavedStateHash: null,
  hasPendingChanges: false,
  saveRetryCount: 0,
  lastSaveError: null,
  startAutoSave: useSaveStore.getState().startAutoSave,
  stopAutoSave: useSaveStore.getState().stopAutoSave,
  saveNow: useSaveStore.getState().saveNow,
  autoSave: useSaveStore.getState().autoSave,
  setDeployedAt: useSaveStore.getState().setDeployedAt,
  triggerAutoSave: useSaveStore.getState().triggerAutoSave,
})
