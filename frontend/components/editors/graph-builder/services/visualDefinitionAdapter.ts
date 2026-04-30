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
    graphStateFields: (definitionPayload.graphStateFields as any[]) ?? [],
    fallbackNodeId: (definitionPayload.fallbackNodeId as string) ?? null,
    agentId,
    versionId,
    workspaceId,
  }
}

export const visualDefinitionAdapter = {
  async load(agentId: string, versionId: string, workspaceId: string): Promise<GraphState> {
    const version = await agentVersionService.get(agentId, versionId, workspaceId)
    return toGraphState(version.definition_payload, agentId, versionId, workspaceId)
  },

  async loadVersionGraphState(
    agentId: string,
    versionId: string,
    workspaceId: string,
  ): Promise<LoadedVersionGraphState> {
    const version = await agentVersionService.get(agentId, versionId, workspaceId)
    const rawPayload = version.definition_payload ?? {}

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
    const updated = await agentVersionService.update(agentId, versionId, workspaceId, {
      definition_payload: mergedPayload,
    })
    return { versionId: updated.id }
  },

  sendBeaconSave(
    agentId: string,
    versionId: string,
    workspaceId: string,
    graphState: { nodes: unknown[]; edges: unknown[]; viewport?: unknown },
  ): void {
    const url = `${API_BASE}/agents/${agentId}/versions/${versionId}?workspace_id=${workspaceId}`
    const body = JSON.stringify({ definition_payload: graphState })
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
