/**
 * Graphs Query Hooks
 *
 * Unified management of all graph-related API calls
 * - Use React Query for caching and deduplication
 * - Avoid duplicate requests
 * - Provide consistent queryKey management
 */
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import type { Node, Edge } from 'reactflow'

import type { AgentGraph } from '@/app/workspace/[workspaceId]/[agentId]/services/agentService'
import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api-client'
import { createLogger } from '@/lib/logs/console/logger'
import type { 
  GraphDeploymentVersion as DeploymentVersion,
  GraphDeploymentStatus as DeploymentStatus 
} from '@/services/graphDeploymentService'

import { STALE_TIME, CACHE_TIME } from './constants'

// ============================================================================
// Types - Import unified type definitions from service layer
// ============================================================================

// Re-export types for other modules to use
export type { AgentGraph, DeploymentVersion, DeploymentStatus }

const logger = createLogger('GraphsQueries')

// GraphState is a type specific to this module
export interface GraphState {
  nodes: Node[]
  edges: Edge[]
  viewport?: { x: number; y: number; zoom: number }
  variables?: { context?: Record<string, unknown> }
}

// ============================================================================
// Query Key Factory
// ============================================================================

export const graphKeys = {
  all: ['graphs'] as const,
  
  // Lists
  lists: () => [...graphKeys.all, 'list'] as const,
  list: (workspaceId?: string) => [...graphKeys.lists(), workspaceId] as const,
  deployed: () => [...graphKeys.all, 'deployed'] as const,
  
  // Details
  details: () => [...graphKeys.all, 'detail'] as const,
  detail: (id: string) => [...graphKeys.details(), id] as const,
  
  // Graph state (nodes, edges)
  states: () => [...graphKeys.all, 'state'] as const,
  state: (id: string) => [...graphKeys.states(), id] as const,
  
  // Deployment
  deployments: () => [...graphKeys.all, 'deployment'] as const,
  deployment: (id: string) => [...graphKeys.deployments(), id] as const,
  
  // Deployment versions
  versions: (id: string) => [...graphKeys.deployments(), id, 'versions'] as const,
  
  // Copilot history
  copilotHistory: (id: string) => [...graphKeys.all, 'copilot', id] as const,
} as const

// ============================================================================
// Fetch Functions
// ============================================================================

async function fetchGraphs(workspaceId?: string): Promise<AgentGraph[]> {
  const url = workspaceId ? `graphs?workspaceId=${workspaceId}` : 'graphs'
  const response = await apiGet<{ data: AgentGraph[] }>(url)
  return response.data || []
}

async function fetchDeployedGraphs(): Promise<AgentGraph[]> {
  const response = await apiGet<{ data: AgentGraph[] }>('graphs/deployed')
  return response.data || []
}

async function fetchGraphState(graphId: string): Promise<GraphState> {
  // apiGet's parseResponse already unwraps { success, data } structure, returns data directly
  const data = await apiGet<GraphState>(`graphs/${graphId}/state`) || { nodes: [], edges: [] }

  // Edge deduplication
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
  
  return data
}

async function fetchDeploymentStatus(graphId: string): Promise<DeploymentStatus> {
  return apiGet<DeploymentStatus>(`graphs/${graphId}/deploy`)
}

async function fetchDeploymentVersions(
  graphId: string,
  page: number = 1,
  pageSize: number = 10
): Promise<{ versions: DeploymentVersion[]; total: number; page: number; pageSize: number; totalPages: number }> {
  // Use correct backend endpoint /deployments (not /deploy/versions)
  return apiGet(`graphs/${graphId}/deployments?page=${page}&page_size=${pageSize}`)
}

// Copilot History type definitions
export interface CopilotHistoryMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string | null
  actions: Array<{ type: string; payload: Record<string, unknown> }> | null
  thought_steps: Array<{ index: number; content: string }> | null
  tool_calls: Array<{ tool: string; input: Record<string, unknown> }> | null
}

// apiGet automatically unwraps { success, data } structure, only returns data part
export interface CopilotHistoryData {
  graph_id: string
  messages: CopilotHistoryMessage[]
  created_at: string | null
  updated_at: string | null
}

async function fetchCopilotHistory(graphId: string): Promise<CopilotHistoryData> {
  return apiGet<CopilotHistoryData>(`graphs/${graphId}/copilot/history`)
}

// ============================================================================
// Query Hooks
// ============================================================================

/**
 * Hook: Get list of all graphs in workspace
 *
 * Use the same queryKey to ensure cache consistency,
 * automatically deduplicate requests when multiple components use this hook
 */
export function useGraphs(workspaceId?: string) {
  return useQuery({
    queryKey: graphKeys.list(workspaceId),
    queryFn: () => fetchGraphs(workspaceId),
    enabled: !!workspaceId,
    staleTime: STALE_TIME.SHORT,
    placeholderData: keepPreviousData,
  })
}

/**
 * Hook: Get list of deployed graphs (for chat interface)
 */
export function useDeployedGraphs() {
  return useQuery({
    queryKey: graphKeys.deployed(),
    queryFn: fetchDeployedGraphs,
    staleTime: STALE_TIME.SHORT,
    placeholderData: keepPreviousData,
  })
}

/**
 * Hook: Get single graph state (nodes, edges, viewport)
 *
 * Unified management of graph state fetching, use React Query for caching and deduplication
 * Avoid multiple components requesting the same graph state simultaneously
 *
 * @param graphId - Graph ID
 * @param options.enabled - Whether to enable query
 * @param options.refetchOnMount - Whether to refetch on mount (default false, use cache)
 */
export function useGraphState(
  graphId?: string,
  options?: { 
    enabled?: boolean
    refetchOnMount?: boolean | 'always'
  }
) {
  return useQuery({
    queryKey: graphKeys.state(graphId || ''),
    queryFn: () => fetchGraphState(graphId!),
    enabled: !!graphId && (options?.enabled !== false),
    staleTime: STALE_TIME.SHORT,
    gcTime: CACHE_TIME.STANDARD,
    refetchOnMount: options?.refetchOnMount ?? false, // default to use cache
    refetchOnWindowFocus: false, // avoid duplicate requests when switching windows
  })
}

/**
 * Hook: Get deployment status of graph
 *
 * This is key to solving duplicate /deploy requests
 * Use React Query's deduplication mechanism
 *
 * @param graphId - Graph ID
 * @param options.enabled - Whether to enable query (for conditional loading)
 */
export function useDeploymentStatus(graphId?: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: graphKeys.deployment(graphId || ''),
    queryFn: () => fetchDeploymentStatus(graphId!),
    enabled: !!graphId && (options?.enabled !== false),
    staleTime: STALE_TIME.SHORT,
    placeholderData: keepPreviousData,
  })
}

/**
 * Hook: Get deployment version history of graph
 *
 * @param graphId - Graph ID
 * @param page - Page number
 * @param pageSize - Items per page
 * @param options.enabled - Whether to enable query (for conditional loading, e.g., when panel opens)
 */
export function useDeploymentVersions(
  graphId?: string, 
  page: number = 1, 
  pageSize: number = 10,
  options?: { enabled?: boolean }
) {
  return useQuery({
    queryKey: [...graphKeys.versions(graphId || ''), page, pageSize],
    queryFn: () => fetchDeploymentVersions(graphId!, page, pageSize),
    // Only execute when graphId exists and enabled is true (or not specified)
    enabled: !!graphId && (options?.enabled !== false),
    staleTime: STALE_TIME.SHORT,
    placeholderData: keepPreviousData,
  })
}

/**
 * Hook: Get Copilot history
 *
 * Unified management of Copilot history fetching, avoid duplicate fetch function definitions in components
 *
 * @param graphId - Graph ID
 * @param options.enabled - Whether to enable query
 */
export function useCopilotHistory(graphId?: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: graphKeys.copilotHistory(graphId || ''),
    queryFn: () => fetchCopilotHistory(graphId!),
    enabled: !!graphId && (options?.enabled !== false),
    staleTime: STALE_TIME.STANDARD,
    // Don't show old data on first load
    placeholderData: undefined,
  })
}

// ============================================================================
// Mutation Hooks
// ============================================================================

/**
 * Hook: Save graph state
 */
export function useSaveGraphState() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: async (params: {
      graphId: string
      nodes: Node[]
      edges: Edge[]
      viewport?: { x: number; y: number; zoom: number }
      variables?: { context?: Record<string, unknown> }
    }) => {
      await apiPost(`graphs/${params.graphId}/state`, {
        nodes: params.nodes,
        edges: params.edges,
        viewport: params.viewport,
        variables: params.variables,
      })
    },
    onSuccess: (_, variables) => {
      // Update state in cache
      queryClient.setQueryData(graphKeys.state(variables.graphId), {
        nodes: variables.nodes,
        edges: variables.edges,
        viewport: variables.viewport,
        variables: variables.variables,
      })
    },
  })
}

/**
 * Hook: Create new graph
 */
export function useCreateGraph() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: async (params: {
      name: string
      description?: string
      color?: string
      workspaceId?: string | null
      variables?: Record<string, unknown>
    }) => {
      const response = await apiPost<{ data: AgentGraph }>('graphs', params)
      return response.data
    },
    onSuccess: (newGraph, variables) => {
      // Refresh graph list for corresponding workspace
      if (variables.workspaceId) {
        queryClient.invalidateQueries({ queryKey: graphKeys.list(variables.workspaceId) })
      }
    },
  })
}

/**
 * Hook: Update graph information
 */
export function useUpdateGraph() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: async (params: {
      id: string
      name?: string
      description?: string
      color?: string
      workspaceId?: string
    }) => {
      const { id, workspaceId, ...updates } = params
      await apiPut(`graphs/${id}`, updates)
      return { id, workspaceId, ...updates }
    },
    onSuccess: (result) => {
      // Refresh graph list
      if (result.workspaceId) {
        queryClient.invalidateQueries({ queryKey: graphKeys.list(result.workspaceId) })
      }
      // Refresh details
      queryClient.invalidateQueries({ queryKey: graphKeys.detail(result.id) })
    },
  })
}

/**
 * Hook: Delete graph
 */
export function useDeleteGraph() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: async (params: { id: string; workspaceId?: string }) => {
      await apiDelete(`graphs/${params.id}`)
      return params
    },
    onSuccess: (params) => {
      // Refresh graph list
      if (params.workspaceId) {
        queryClient.invalidateQueries({ queryKey: graphKeys.list(params.workspaceId) })
      }
      // Clear related cache
      queryClient.removeQueries({ queryKey: graphKeys.detail(params.id) })
      queryClient.removeQueries({ queryKey: graphKeys.state(params.id) })
      queryClient.removeQueries({ queryKey: graphKeys.deployment(params.id) })
    },
  })
}

/**
 * Hook: Deploy graph
 */
export function useDeployGraph() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: async (params: { graphId: string; name?: string }) => {
      return apiPost<{ message: string; version?: number }>(`graphs/${params.graphId}/deploy`, {
        name: params.name,
      })
    },
    onSuccess: (_, variables) => {
      // Refresh deployment status
      queryClient.invalidateQueries({ queryKey: graphKeys.deployment(variables.graphId) })
      // Refresh version list
      queryClient.invalidateQueries({ queryKey: graphKeys.versions(variables.graphId) })
      // Refresh deployed list
      queryClient.invalidateQueries({ queryKey: graphKeys.deployed() })
    },
  })
}

/**
 * Hook: Cancel graph deployment
 */
export function useUndeployGraph() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: async (graphId: string) => {
      await apiDelete(`graphs/${graphId}/deploy`)
      return graphId
    },
    onSuccess: (graphId) => {
      queryClient.invalidateQueries({ queryKey: graphKeys.deployment(graphId) })
      queryClient.invalidateQueries({ queryKey: graphKeys.deployed() })
    },
  })
}

// ============================================================================
// Helper Hooks
// ============================================================================

/**
 * Helper: Get graph details (search from list cache to avoid extra requests)
 */
export function useGraphFromCache(graphId?: string, workspaceId?: string) {
  const { data: graphs } = useGraphs(workspaceId)
  return graphs?.find(g => g.id === graphId)
}

/**
 * Helper: Refresh all graph data related to workspace
 */
export function useInvalidateGraphs() {
  const queryClient = useQueryClient()
  
  return (workspaceId?: string) => {
    if (workspaceId) {
      queryClient.invalidateQueries({ queryKey: graphKeys.list(workspaceId) })
    } else {
      queryClient.invalidateQueries({ queryKey: graphKeys.lists() })
    }
  }
}

