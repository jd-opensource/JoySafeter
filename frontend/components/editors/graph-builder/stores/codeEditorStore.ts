import { create } from 'zustand'
import { agentVersionService } from '@/services/agentVersionService'

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
  versionId: string | null
  workspaceId: string | null

  setCode: (code: string) => void
  setGraphId: (id: string) => void
  setGraphName: (name: string) => void
  save: () => Promise<void>
  hydrate: (graphId: string, code: string, name: string, versionId: string | null, workspaceId: string | null) => void
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
  versionId: null,
  workspaceId: null,

  setCode: (code) => set({ code, isDirty: code !== get().savedCode }),

  setGraphId: (id) => set({ graphId: id }),
  setGraphName: (name) => set({ graphName: name }),

  save: async () => {
    const { graphId, versionId, workspaceId, code, graphName } = get()
    if (!graphId || !versionId || !workspaceId) return
    set({ isSaving: true })
    try {
      await agentVersionService.update(graphId, versionId, workspaceId, {
        definition_payload: {
          graph_mode: 'code',
          code_content: code,
        },
      })
      set({ savedCode: code, isDirty: false })
    } finally {
      set({ isSaving: false })
    }
  },

  hydrate: (graphId, code, name, versionId, workspaceId) =>
    set({
      graphId,
      code,
      savedCode: code,
      isDirty: false,
      graphName: name,
      isSaving: false,
      versionId: versionId ?? null,
      workspaceId: workspaceId ?? null,
    }),

  reset: () =>
    set({
      code: '',
      savedCode: '',
      isSaving: false,
      isDirty: false,
      graphId: null,
      graphName: null,
      versionId: null,
      workspaceId: null,
    }),
}))
