import { create } from 'zustand'
import { apiPost } from '@/lib/api-client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CodeEditorState {
  code: string
  savedCode: string
  isSaving: boolean
  isDirty: boolean

  graphId: string | null
  graphName: string | null

  setCode: (code: string) => void
  setGraphId: (id: string) => void
  setGraphName: (name: string) => void
  save: () => Promise<void>
  hydrate: (graphId: string, code: string, name: string) => void
  reset: () => void
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useCodeEditorStore = create<CodeEditorState>((set, get) => ({
  code: '',
  savedCode: '',
  isSaving: false,
  isDirty: false,
  graphId: null,
  graphName: null,

  setCode: (code) => set({ code, isDirty: code !== get().savedCode }),

  setGraphId: (id) => set({ graphId: id }),
  setGraphName: (name) => set({ graphName: name }),

  save: async () => {
    const { graphId, code, graphName } = get()
    if (!graphId) return
    set({ isSaving: true })
    try {
      await apiPost(`graphs/${graphId}/code/save`, { code, name: graphName })
      set({ savedCode: code, isDirty: false })
    } finally {
      set({ isSaving: false })
    }
  },

  hydrate: (graphId, code, name) =>
    set({
      graphId,
      code,
      savedCode: code,
      isDirty: false,
      graphName: name,
      isSaving: false,
    }),

  reset: () =>
    set({
      code: '',
      savedCode: '',
      isSaving: false,
      isDirty: false,
      graphId: null,
      graphName: null,
    }),
}))
