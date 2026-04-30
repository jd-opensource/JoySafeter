import { agentVersionService } from '@/services/agentVersionService'
import { API_BASE } from '@/lib/api-client'
import type { DefinitionKind } from '@/types/agent'
import type { GraphState } from '../utils/saveManager'

export interface LoadedVersionGraphState {
  graphState: GraphState
  definitionKind: DefinitionKind
  versionStatus: 'draft' | 'frozen'
  rawPayload: Record<string, unknown>
}

const payloadCache = new Map<string, Record<string, unknown>>()

function cacheKey(agentId: string, versionId: string, workspaceId: string): string {
  return `${workspaceId}:${agentId}:${versionId}`
}

function cachePayload(
  agentId: string,
  versionId: string,
  workspaceId: string,
  payload: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  const definitionPayload = payload ?? {}
  payloadCache.set(cacheKey(agentId, versionId, workspaceId), definitionPayload)
  return definitionPayload
}

function getCachedPayload(
  agentId: string,
  versionId: string,
  workspaceId: string,
): Record<string, unknown> {
  return payloadCache.get(cacheKey(agentId, versionId, workspaceId)) ?? {}
}

function toGraphState(
  payload: Record<string, unknown> | null | undefined,
  agentId: string,
  versionId: string,
  workspaceId: string,
): GraphState {
  const definitionPayload = payload ?? {}

  return {
    graphId: (definitionPayload.graphId as string) ?? null,
    graphName: (definitionPayload.graphName as string) ?? null,
    nodes: (definitionPayload.nodes as any[]) ?? [],
    edges: (definitionPayload.edges as any[]) ?? [],
    viewport: (definitionPayload.viewport as { x: number; y: number; zoom: number }) ?? {
      x: 0,
      y: 0,
      zoom: 1,
    },
    graphStateFields:
      (definitionPayload.graphStateFields as any[]) ?? (definitionPayload.state_fields as any[]) ?? [],
    fallbackNodeId:
      (definitionPayload.fallbackNodeId as string) ??
      (definitionPayload.fallback_node_id as string) ??
      null,
    agentId,
    versionId,
    workspaceId,
  }
}

export const visualDefinitionAdapter = {
  async load(agentId: string, versionId: string, workspaceId: string): Promise<GraphState> {
    const version = await agentVersionService.get(agentId, versionId, workspaceId)
    const rawPayload = cachePayload(agentId, versionId, workspaceId, version.definition_payload)
    return toGraphState(rawPayload, agentId, versionId, workspaceId)
  },

  async loadVersionGraphState(
    agentId: string,
    versionId: string,
    workspaceId: string,
  ): Promise<LoadedVersionGraphState> {
    const version = await agentVersionService.get(agentId, versionId, workspaceId)
    const rawPayload = cachePayload(agentId, versionId, workspaceId, version.definition_payload)

    return {
      graphState: toGraphState(rawPayload, agentId, versionId, workspaceId),
      definitionKind: version.definition_kind,
      versionStatus: version.status,
      rawPayload,
    }
  },

  async save(
    agentId: string,
    versionId: string,
    workspaceId: string,
    graphState: Partial<GraphState>,
  ): Promise<{ versionId: string }> {
    const current = await agentVersionService.get(agentId, versionId, workspaceId)
    const mergedPayload = {
      ...(current.definition_payload ?? {}),
      ...graphState,
    }
    cachePayload(agentId, versionId, workspaceId, mergedPayload)
    const updated = await agentVersionService.update(agentId, versionId, workspaceId, {
      definition_payload: mergedPayload,
    })
    cachePayload(agentId, updated.id, workspaceId, mergedPayload)
    return { versionId: updated.id }
  },

  sendBeaconSave(
    agentId: string,
    versionId: string,
    workspaceId: string,
    graphState: { nodes: unknown[]; edges: unknown[]; viewport?: unknown },
  ): void {
    const url = `${API_BASE}/agents/${agentId}/versions/${versionId}?workspace_id=${workspaceId}`
    const mergedPayload = {
      ...getCachedPayload(agentId, versionId, workspaceId),
      ...graphState,
    }
    const body = JSON.stringify({ definition_payload: mergedPayload })
    fetch(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => {})
  },

  async createDraft(
    agentId: string,
    workspaceId: string,
    basePayload?: Record<string, unknown>,
  ): Promise<string> {
    const version = await agentVersionService.create(agentId, workspaceId, {
      definition_kind: 'graph',
      definition_payload: basePayload || {},
    })
    return version.id
  },
}
