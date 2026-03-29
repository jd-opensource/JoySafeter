import { create } from 'zustand'
import { apiPost } from '@/lib/api-client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ParseError {
  line: number | null
  message: string
  severity: 'error' | 'warning'
}

export interface PreviewNode {
  id: string
  type: string
  position: { x: number; y: number }
  data: Record<string, any>
}

export interface PreviewEdge {
  id: string
  source: string
  target: string
  label?: string
  type?: string
}

export interface PreviewData {
  nodes: PreviewNode[]
  edges: PreviewEdge[]
}

interface CodeEditorState {
  // State
  code: string
  savedCode: string
  parseResult: Record<string, any> | null
  preview: PreviewData | null
  parseErrors: ParseError[]
  isParsing: boolean
  isSaving: boolean
  isDirty: boolean

  // Graph metadata
  graphId: string | null
  graphName: string | null

  // Actions
  setCode: (code: string) => void
  setGraphId: (id: string) => void
  setGraphName: (name: string) => void
  setParseResult: (
    result: Record<string, any> | null,
    preview: PreviewData | null,
    errors: ParseError[],
  ) => void
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
  parseResult: null,
  preview: null,
  parseErrors: [],
  isParsing: false,
  isSaving: false,
  isDirty: false,
  graphId: null,
  graphName: null,

  setCode: (code) => set({ code, isDirty: code !== get().savedCode }),

  setGraphId: (id) => set({ graphId: id }),
  setGraphName: (name) => set({ graphName: name }),

  setParseResult: (result, preview, errors) =>
    set({ parseResult: result, preview, parseErrors: errors, isParsing: false }),

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
      parseResult: null,
      preview: null,
      parseErrors: [],
    }),

  reset: () =>
    set({
      code: '',
      savedCode: '',
      parseResult: null,
      preview: null,
      parseErrors: [],
      isParsing: false,
      isSaving: false,
      isDirty: false,
      graphId: null,
      graphName: null,
    }),
}))
