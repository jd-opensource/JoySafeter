import { agentVersionService } from '@/services/agentVersionService'
import { API_BASE } from '@/lib/api-client'
import type { EngineKind } from '@/types/agent'
import type { GraphState } from '../utils/saveManager'

export interface LoadedVersionGraphState {
  graphState: GraphState
  engineKind: EngineKind
  versionStatus: 'draft' | 'frozen'
  rawPayload: Record<string, unknown>
}

const payloadCache = new Map<string, Record<string, unknown>>()

function cacheKey(agentId: string, versionId: string, projectId: string): string {
  return `${projectId}:${agentId}:${versionId}`
}

function cachePayload(
  agentId: string,
  versionId: string,
  projectId: string,
  payload: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  const definitionPayload = payload ?? {}
  payloadCache.set(cacheKey(agentId, versionId, projectId), definitionPayload)
  return definitionPayload
}

function getCachedPayload(
  agentId: string,
  versionId: string,
  projectId: string,
): Record<string, unknown> {
  return payloadCache.get(cacheKey(agentId, versionId, projectId)) ?? {}
}

function toGraphState(
  payload: Record<string, unknown> | null | undefined,
  agentId: string,
  versionId: string,
  projectId: string,
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
      (definitionPayload.graphStateFields as any[]) ??
      (definitionPayload.state_fields as any[]) ??
      [],
    fallbackNodeId:
      (definitionPayload.fallbackNodeId as string) ??
      (definitionPayload.fallback_node_id as string) ??
      null,
    agentId,
    versionId,
    projectId,
  }
}

export const visualDefinitionAdapter = {
  async load(agentId: string, versionId: string, projectId: string): Promise<GraphState> {
    const version = await agentVersionService.get(agentId, versionId)
    const rawPayload = cachePayload(agentId, versionId, projectId, version.definition_payload)
    return toGraphState(rawPayload, agentId, versionId, projectId)
  },

  async loadVersionGraphState(
    agentId: string,
    versionId: string,
    projectId: string,
  ): Promise<LoadedVersionGraphState> {
    const version = await agentVersionService.get(agentId, versionId)
    const rawPayload = cachePayload(agentId, versionId, projectId, version.definition_payload)

    return {
      graphState: toGraphState(rawPayload, agentId, versionId, projectId),
      engineKind: version.engine_kind,
      versionStatus: version.status,
      rawPayload,
    }
  },

  async save(
    agentId: string,
    versionId: string,
    projectId: string,
    graphState: Partial<GraphState>,
  ): Promise<{ versionId: string }> {
    const current = await agentVersionService.get(agentId, versionId)
    const mergedPayload = {
      ...(current.definition_payload ?? {}),
      ...graphState,
    }
    cachePayload(agentId, versionId, projectId, mergedPayload)
    const updated = await agentVersionService.update(agentId, versionId, {
      definition_payload: mergedPayload,
    })
    cachePayload(agentId, updated.id, projectId, mergedPayload)
    return { versionId: updated.id }
  },

  sendBeaconSave(
    agentId: string,
    versionId: string,
    projectId: string,
    graphState: { nodes: unknown[]; edges: unknown[]; viewport?: unknown },
  ): void {
    const url = `${API_BASE}/agents/${agentId}/versions/${versionId}?project_id=${projectId}`
    const mergedPayload = {
      ...getCachedPayload(agentId, versionId, projectId),
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
    projectId: string,
    basePayload?: Record<string, unknown>,
  ): Promise<string> {
    const version = await agentVersionService.create(agentId, {
      engine_kind: 'langgraph_visual',
      definition_payload: basePayload || {},
    })
    return version.id
  },
}
