import { create } from 'zustand'

import type { CustomTool, CustomToolsActions, CustomToolsState } from './types'

/**
 * Mock custom tools store
 * Uses mock data for development
 */

const mockTools: CustomTool[] = [
  {
    id: 'custom-tool-1',
    name: 'Custom API Tool',
    description: 'A custom tool for API calls',
    schema: {
      id: 'custom-tool-1',
      name: 'Custom API Tool',
      description: 'A custom tool for API calls',
      parameters: [
        { name: 'url', type: 'string', required: true, description: 'API URL' },
        { name: 'method', type: 'string', required: false, description: 'HTTP method' },
      ],
      endpoint: '/api/custom',
      method: 'POST',
    },
    createdAt: new Date('2024-01-01'),
    updatedAt: new Date(),
  },
]

type CustomToolsStore = CustomToolsState & CustomToolsActions

export const useCustomToolsStore = create<CustomToolsStore>((set, get) => ({
  // State
  tools: mockTools.reduce(
    (acc, tool) => {
      acc[tool.id] = tool
      return acc
    },
    {} as Record<string, CustomTool>
  ),
  isLoading: false,
  error: null,

  // Actions
  setTools: (tools) => {
    set({
      tools: tools.reduce(
        (acc, tool) => {
          acc[tool.id] = tool
          return acc
        },
        {} as Record<string, CustomTool>
      ),
    })
  },

  addTool: (tool) => {
    set((state) => ({
      tools: { ...state.tools, [tool.id]: tool },
    }))
  },

  updateTool: (id, updates) => {
    set((state) => {
      const existing = state.tools[id]
      if (!existing) return state
      return {
        tools: {
          ...state.tools,
          [id]: { ...existing, ...updates, updatedAt: new Date() },
        },
      }
    })
  },

  removeTool: (id) => {
    set((state) => {
      const { [id]: _, ...rest } = state.tools
      return { tools: rest }
    })
  },

  getTool: (id) => get().tools[id],

  getToolAsync: async (id) => {
    return get().tools[id]
  },

  getAllTools: () => Object.values(get().tools),

  setLoading: (loading) => set({ isLoading: loading }),

  setError: (error) => set({ error }),
}))
