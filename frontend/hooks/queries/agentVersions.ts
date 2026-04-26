/**
 * Agent Version Queries
 *
 * React Query hooks for AgentVersion, nested under Agent.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { Node, Edge } from 'reactflow'

import { agentVersionService } from '@/services/agentVersionService'
import type {
  AgentVersion,
  CreateAgentVersionRequest,
  UpdateAgentVersionRequest,
} from '@/types/agent'

import { STALE_TIME, CACHE_TIME } from './constants'
import { agentKeys } from './agents'

// ==================== Query Keys ====================

export const versionKeys = {
  all: (agentId: string, workspaceId: string) =>
    [...agentKeys.detail(agentId, workspaceId), 'versions'] as const,
  list: (agentId: string, workspaceId: string) =>
    [...versionKeys.all(agentId, workspaceId), 'list'] as const,
  detail: (agentId: string, versionId: string, workspaceId: string) =>
    [...versionKeys.all(agentId, workspaceId), 'detail', versionId] as const,
  graphState: (agentId: string, versionId: string, workspaceId: string) =>
    [...versionKeys.detail(agentId, versionId, workspaceId), 'graphState'] as const,
}

// ==================== Query Hooks ====================

export function useVersions(
  agentId: string,
  workspaceId: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: versionKeys.list(agentId, workspaceId),
    queryFn: async (): Promise<AgentVersion[]> => {
      const versions = await agentVersionService.list(agentId, workspaceId)
      return versions || []
    },
    enabled: Boolean(agentId) && Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.STANDARD,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  })
}

export function useVersion(
  agentId: string,
  versionId: string,
  workspaceId: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: versionKeys.detail(agentId, versionId, workspaceId),
    queryFn: () => agentVersionService.get(agentId, versionId, workspaceId),
    enabled:
      Boolean(agentId) &&
      Boolean(versionId) &&
      Boolean(workspaceId) &&
      options?.enabled !== false,
    staleTime: STALE_TIME.STANDARD,
  })
}

// ==================== Mutation Hooks ====================

export function useCreateVersion() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      agentId,
      workspaceId,
      ...data
    }: CreateAgentVersionRequest & { agentId: string; workspaceId: string }) => {
      return agentVersionService.create(agentId, workspaceId, data)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: versionKeys.all(variables.agentId, variables.workspaceId),
      })
      queryClient.invalidateQueries({
        queryKey: agentKeys.detail(variables.agentId, variables.workspaceId),
      })
    },
  })
}

export function useUpdateVersion() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      agentId,
      versionId,
      workspaceId,
      ...data
    }: UpdateAgentVersionRequest & {
      agentId: string
      versionId: string
      workspaceId: string
    }) => {
      return agentVersionService.update(agentId, versionId, workspaceId, data)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: versionKeys.all(variables.agentId, variables.workspaceId),
      })
    },
  })
}

// ==================== Graph State from Version ====================

export interface VersionGraphState {
  nodes: Node[]
  edges: Edge[]
  viewport?: { x: number; y: number; zoom: number }
  variables?: Record<string, unknown>
  definitionKind?: string
  versionStatus?: 'draft' | 'frozen'
}

function toVersionGraphState(payload: Record<string, unknown>): VersionGraphState {
  const edges = (payload.edges as Edge[]) ?? []
  const seenEdges = new Set<string>()
  const deduplicatedEdges = edges.filter((edge) => {
    const key = `${edge.source}-${edge.target}`
    if (seenEdges.has(key)) return false
    seenEdges.add(key)
    return true
  })

  return {
    nodes: (payload.nodes as Node[]) ?? [],
    edges: deduplicatedEdges,
    viewport: (payload.viewport as { x: number; y: number; zoom: number }) ?? undefined,
    variables: {
      state_fields: payload.graphStateFields ?? payload.state_fields,
      fallback_node_id: payload.fallbackNodeId ?? payload.fallback_node_id,
      graph_mode: payload.graph_mode,
      code_content: payload.code_content,
      context: payload.context,
    },
  }
}

/**
 * Load graph state from agent version definition_payload.
 * New-architecture equivalent of useGraphState — returns the same shape
 * (nodes, edges, viewport, variables) so AgentBuilder can consume it directly.
 */
export function useVersionGraphState(
  agentId?: string,
  versionId?: string,
  workspaceId?: string,
  options?: {
    enabled?: boolean
    refetchOnMount?: boolean | 'always'
  },
) {
  return useQuery({
    queryKey: versionKeys.graphState(agentId || '', versionId || '', workspaceId || ''),
    queryFn: async (): Promise<VersionGraphState> => {
      const version = await agentVersionService.get(agentId!, versionId!, workspaceId!)
      return {
        ...toVersionGraphState(version.definition_payload),
        definitionKind: version.definition_kind,
        versionStatus: version.status as 'draft' | 'frozen',
      }
    },
    enabled:
      Boolean(agentId) &&
      Boolean(versionId) &&
      Boolean(workspaceId) &&
      options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    gcTime: CACHE_TIME.STANDARD,
    refetchOnMount: options?.refetchOnMount ?? false,
    refetchOnWindowFocus: false,
  })
}
