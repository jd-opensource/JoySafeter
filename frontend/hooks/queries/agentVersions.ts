/**
 * Agent Version Queries
 *
 * React Query hooks for AgentVersion, nested under Agent.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { Node, Edge } from 'reactflow'

import { agentVersionService } from '@/services/agentVersionService'
import {
  visualDefinitionAdapter,
  type LoadedVersionGraphState,
} from '@/components/editors/graph-builder/services/visualDefinitionAdapter'
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

export function useVersions(agentId: string, workspaceId: string, options?: { enabled?: boolean }) {
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
      Boolean(agentId) && Boolean(versionId) && Boolean(workspaceId) && options?.enabled !== false,
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

function toVersionGraphState({
  graphState,
  rawPayload,
}: LoadedVersionGraphState): VersionGraphState {
  const edges = graphState.edges ?? []
  const seenEdges = new Set<string>()
  const deduplicatedEdges = edges.filter((edge) => {
    const key = `${edge.source}-${edge.target}`
    if (seenEdges.has(key)) return false
    seenEdges.add(key)
    return true
  })

  return {
    nodes: graphState.nodes ?? [],
    edges: deduplicatedEdges,
    viewport: graphState.viewport,
    variables: {
      state_fields: graphState.graphStateFields ?? rawPayload.state_fields,
      fallback_node_id: graphState.fallbackNodeId ?? rawPayload.fallback_node_id,
      graph_mode: rawPayload.graph_mode,
      code_content: rawPayload.code_content,
      context: rawPayload.context,
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
      const versionState = await visualDefinitionAdapter.loadVersionGraphState(
        agentId!,
        versionId!,
        workspaceId!,
      )
      return {
        ...toVersionGraphState(versionState),
        definitionKind: versionState.definitionKind,
        versionStatus: versionState.versionStatus,
      }
    },
    enabled:
      Boolean(agentId) && Boolean(versionId) && Boolean(workspaceId) && options?.enabled !== false,
    staleTime: STALE_TIME.SHORT,
    gcTime: CACHE_TIME.STANDARD,
    refetchOnMount: options?.refetchOnMount ?? false,
    refetchOnWindowFocus: false,
  })
}
