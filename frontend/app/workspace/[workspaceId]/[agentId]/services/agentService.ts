'use client'

import { Node, Edge } from 'reactflow'

import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api-client'

import { migrateGraphData, needsMigration } from './dataMigration'
import { modelService } from './modelService'

// --- Types ---

export interface AgentGraph {
  id: string
  name: string
  description?: string | null
  color?: string
  isDeployed?: boolean
  workspaceId?: string | null
  parentId?: string | null
  folderId?: string | null
  variables?: Record<string, unknown>
  createdAt: string
  updatedAt: string
  nodeCount?: number
  nodes?: Node[]
  edges?: Edge[]
}

export interface ModelOption {
  id: string
  label: string
  provider: string // provider_display_name (for display)
  provider_name: string
  isAvailable?: boolean
  isDefault?: boolean
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


const GRAPH_ID_CACHE_KEY = 'current_graph_id'
const GRAPH_NAME_CACHE_KEY = 'current_graph_name'
const getCachedGraphId = (): string | null => {
  try {
    return localStorage.getItem(GRAPH_ID_CACHE_KEY)
  } catch {
    return null
  }
}

const setCachedGraphId = (graphId: string): void => {
  try {
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
  async getInitialGraph(): Promise<{ nodes: Node[]; edges: Edge[] }> {
    return { nodes: [], edges: [] }
  },

  async listGraphs(workspaceId?: string): Promise<AgentGraph[]> {
    const url = workspaceId ? `graphs?workspaceId=${workspaceId}` : 'graphs'
    const response = await apiGet<{ data: AgentGraph[] }>(url)
    return response.data || []
  },

  async saveGraph(params: {
    name: string
    nodes: Node[]
    edges: Edge[]
    viewport?: { x: number; y: number; zoom: number }
    description?: string
    color?: string
    variables?: { context?: Record<string, unknown> }
    workspaceId?: string | null
  }): Promise<{ graphId: string }> {
    let graphId = getCachedGraphId()

    if (!graphId) {
      const createResponse = await apiPost<{ data: { id: string } }>('graphs', {
        name: params.name,
        description: params.description || '',
        color: params.color || '',
        variables: params.variables || {},
        workspaceId: params.workspaceId,
      })
      graphId = createResponse.data.id
      setCachedGraphId(graphId)
      setCachedGraphName(params.name)
    }

    const seenEdges = new Set<string>()
    const deduplicatedEdges = params.edges.filter(edge => {
      const key = `${edge.source}-${edge.target}`
      if (seenEdges.has(key)) {
        return false
      }
      seenEdges.add(key)
      return true
    })

    await apiPost(`graphs/${graphId}/state`, {
      nodes: params.nodes,
      edges: deduplicatedEdges,
      viewport: params.viewport,
    })

    return { graphId }
  },

  async saveGraphState(params: {
    graphId: string
    nodes: Node[]
    edges: Edge[]
    viewport?: { x: number; y: number; zoom: number }
    variables?: {
      context?: Record<string, unknown>
      state_fields?: any[]
      [key: string]: unknown
    }
  }): Promise<void> {
    const seenEdges = new Set<string>()
    const deduplicatedEdges = params.edges.filter(edge => {
      const key = `${edge.source}-${edge.target}`
      if (seenEdges.has(key)) {
        return false
      }
      seenEdges.add(key)
      return true
    })

    await apiPost(`graphs/${params.graphId}/state`, {
      nodes: params.nodes,
      edges: deduplicatedEdges,
      viewport: params.viewport,
      variables: params.variables,
    })
  },

  async loadGraphState(
    graphId: string
  ): Promise<{
    nodes: Node[]
    edges: Edge[]
    viewport?: { x: number; y: number; zoom: number }
    variables?: { context?: Record<string, unknown> }
  }> {
    const response = await apiGet<{
      data: {
        nodes: Node[]
        edges: Edge[]
        viewport?: { x: number; y: number; zoom: number }
        variables?: { context?: Record<string, unknown> }
      }
    }>(`graphs/${graphId}/state`)
    setCachedGraphId(graphId)

    let data = response.data || { nodes: [], edges: [] }

    if (data.edges && data.edges.length > 0) {
      const seenEdges = new Set<string>()
      data.edges = data.edges.filter(edge => {
        const key = `${edge.source}-${edge.target}`
        if (seenEdges.has(key)) {
          return false
        }
        seenEdges.add(key)
        return true
      })
    }

    // Apply data migration if needed
    if (data.nodes && data.edges && needsMigration(data.nodes, data.edges)) {
      const migrated = migrateGraphData(data.nodes, data.edges)
      data = {
        ...data,
        nodes: migrated.nodes,
        edges: migrated.edges,
      }
    }

    return data
  },

  async deleteGraph(id: string): Promise<void> {
    await apiDelete(`graphs/${id}`)
  },

  /**
   * Create a new Graph (creates metadata only, without node state)
   */
  async createGraph(params: {
    name: string
    description?: string
    color?: string
    variables?: Record<string, unknown>
    workspaceId?: string | null
  }): Promise<AgentGraph> {
    clearCachedGraphId()
    clearCachedGraphName()

    const response = await apiPost<{ data: AgentGraph }>('graphs', {
      name: params.name,
      description: params.description || '',
      color: params.color || '',
      variables: params.variables || {},
      workspaceId: params.workspaceId,
    })

    return response.data
  },

  /**
   * Update Graph metadata (name, description, color, etc.)
   */
  async updateGraph(
    id: string,
    params: {
      name?: string
      description?: string
      color?: string
      folderId?: string | null
    }
  ): Promise<void> {
    await apiPut(`graphs/${id}`, params)
  },

  /**
   * Duplicate a Graph
   * @param id Original Graph ID
   * @param newName New Graph name (optional, defaults to adding "(copy)" suffix)
   * @param workspaceId Target workspace ID
   * @returns New Graph ID
   */
  async duplicateGraph(
    id: string,
    options?: {
      newName?: string
      workspaceId?: string | null
    }
  ): Promise<string> {
    // Load original graph state
    const state = await this.loadGraphState(id)

    // Get original graph metadata
    const graphs = await this.listGraphs(options?.workspaceId || undefined)
    const originalGraph = graphs.find((g) => g.id === id)

    if (!originalGraph) {
      throw new Error('Graph not found')
    }

    clearCachedGraphId()
    clearCachedGraphName()

    // Create new graph
    const createResponse = await apiPost<{ data: { id: string } }>('graphs', {
      name: options?.newName || `${originalGraph.name} (copy)`,
      description: originalGraph.description || '',
      color: originalGraph.color || '',
      variables: originalGraph.variables || {},
      workspaceId: options?.workspaceId || originalGraph.workspaceId || null,
    })

    const newGraphId = createResponse.data.id

    // Copy state
    await apiPost(`graphs/${newGraphId}/state`, {
      nodes: state.nodes,
      edges: state.edges,
      viewport: state.viewport,
    })

    return newGraphId
  },

  /**
   * Move Graph to specified folder
   */
  async moveToFolder(graphId: string, folderId: string | null): Promise<void> {
    await apiPut(`graphs/${graphId}`, {
      folderId: folderId || null,
    })
  },

  async getModels(workspaceId?: string): Promise<ModelOption[]> {
    try {
      const models = await modelService.getAvailableModels('chat', workspaceId)
      return models.map((model) => ({
        id: `${model.provider_name}:${model.name}`,
        label: model.display_name || model.name,
        provider: model.provider_display_name || model.provider_name, // for display
        provider_name: model.provider_name,
        isAvailable: model.is_available,
        isDefault: model.is_default,
      }))
    } catch (error) {
      return []
    }
  },

  /**
   * Get default model ID
   * Returns model marked as default first, or first available model if no default is set
   * @param workspaceId Workspace ID (optional)
   * @returns Default model ID, or empty string if no available models
   */
  async getDefaultModelId(workspaceId?: string): Promise<string> {
    try {
      const models = await this.getModels(workspaceId)

      // Find model marked as default
      const defaultModel = models.find((m) => m.isDefault === true && m.isAvailable !== false)
      if (defaultModel) {
        return defaultModel.id
      }

      // If no default model, return first available model
      const firstAvailable = models.find((m) => m.isAvailable !== false)
      if (firstAvailable) {
        return firstAvailable.id
      }

      // If no available models, return empty string
      return ''
    } catch (error) {
      console.error('Failed to get default model:', error)
      // If fetch fails, return empty string to let caller use hardcoded fallback
      return ''
    }
  },

  async getBuiltinTools(): Promise<ToolOption[]> {
    try {
      // apiGet automatically unwraps response.data, directly return tools array
      const tools = await apiGet<Array<{
        id: string
        label: string
        name: string
        description?: string
        tool_type: string
        category?: string | null
        tags?: string[]
        mcp_server?: string | null
      }>>('tools/builtin')
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
    } catch (error) {
      return []
    }
  },

  async getMcpServers(): Promise<string[]> {
    return []
  },

  async addMcpServer(_url: string): Promise<void> {
    return
  },

  /**
   * Get available skills for the agent
   * Uses the skills API to fetch all skills the user has access to
   */
  async getAvailableSkills(): Promise<SkillOption[]> {
    try {
      const response = await apiGet<{
        data: Array<{
          id: string
          name: string
          description: string
          tags?: string[]
        }>
      }>('skills?include_public=true')
      const skills = response.data || []
      return skills.map((skill) => ({
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
