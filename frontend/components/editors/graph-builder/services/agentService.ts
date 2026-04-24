'use client'

import { apiGet } from '@/lib/api-client'

import { modelService } from './modelService'

// --- Types ---

export interface ModelOption {
  id: string
  name: string // raw model name from API (e.g. "qwen3.5:latest")
  label: string
  provider: string // provider_display_name (for display)
  provider_name: string
  isAvailable?: boolean
}

export interface ToolOption {
  id: string
  label: string
  description?: string
  name?: string
  toolType?: string
  category?: string | null
  tags?: string[]
  mcpServer?: string | null
  raw?: unknown
}

export interface SkillOption {
  id: string
  name: string
  description: string
  tags: string[]
}

const isValidUUID = (str: string): boolean => {
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
  return uuidRegex.test(str)
}

const GRAPH_ID_CACHE_KEY = 'current_graph_id'
const GRAPH_NAME_CACHE_KEY = 'current_graph_name'
const getCachedGraphId = (): string | null => {
  try {
    const id = localStorage.getItem(GRAPH_ID_CACHE_KEY)
    if (id && !isValidUUID(id)) {
      return null
    }
    return id
  } catch {
    return null
  }
}

const setCachedGraphId = (graphId: string): void => {
  try {
    if (!isValidUUID(graphId)) {
      console.warn('[agentService] Invalid graphId passed to setCachedGraphId, ignored:', graphId)
      return
    }
    localStorage.setItem(GRAPH_ID_CACHE_KEY, graphId)
  } catch {
    // Silent fail
  }
}

const clearCachedGraphId = (): void => {
  try {
    localStorage.removeItem(GRAPH_ID_CACHE_KEY)
  } catch {
    // Silent fail
  }
}

const getCachedGraphName = (): string | null => {
  try {
    return localStorage.getItem(GRAPH_NAME_CACHE_KEY)
  } catch {
    return null
  }
}

const setCachedGraphName = (graphName: string): void => {
  try {
    localStorage.setItem(GRAPH_NAME_CACHE_KEY, graphName)
  } catch {
    // Silent fail
  }
}

const clearCachedGraphName = (): void => {
  try {
    localStorage.removeItem(GRAPH_NAME_CACHE_KEY)
  } catch {
    // Silent fail
  }
}

export const agentService = {
  async getModels(): Promise<ModelOption[]> {
    try {
      const models = await modelService.getAvailableModels('chat')
      return models.map((model) => ({
        id: `${model.provider_name}:${model.name}`,
        name: model.name,
        label: model.display_name || model.name,
        provider: model.provider_display_name || model.provider_name, // for display
        provider_name: model.provider_name,
        isAvailable: model.is_available,
      }))
    } catch {
      return []
    }
  },

  async getBuiltinTools(): Promise<ToolOption[]> {
    try {
      // apiGet automatically unwraps response.data, directly return tools array
      const tools = await apiGet<
        Array<{
          id: string
          label: string
          name: string
          description?: string
          tool_type: string
          category?: string | null
          tags?: string[]
          mcp_server?: string | null
        }>
      >('tools/builtin')
      return (tools || []).map((tool) => ({
        id: tool.id,
        label: tool.label,
        description: tool.description,
        name: tool.name,
        toolType: tool.tool_type,
        category: tool.category ?? null,
        tags: tool.tags ?? [],
        mcpServer: tool.mcp_server ?? null,
        raw: tool,
      }))
    } catch {
      return []
    }
  },

  /**
   * Get available skills for the agent
   * Uses the skills API to fetch all skills the user has access to
   */
  async getAvailableSkills(): Promise<SkillOption[]> {
    try {
      const skills = await apiGet<
        Array<{
          id: string
          name: string
          description: string
          tags?: string[]
        }>
      >('skills?include_public=true')
      return (skills || []).map((skill) => ({
        id: skill.id,
        name: skill.name,
        description: skill.description,
        tags: skill.tags || [],
      }))
    } catch (error) {
      console.error('Failed to fetch skills from backend:', error)
      return []
    }
  },

  // --- Cache Management ---
  getCachedGraphId: getCachedGraphId,
  setCachedGraphId: setCachedGraphId,
  clearCachedGraphId: clearCachedGraphId,
  getCachedGraphName: getCachedGraphName,
  setCachedGraphName: setCachedGraphName,
  clearCachedGraphName: clearCachedGraphName,
}
