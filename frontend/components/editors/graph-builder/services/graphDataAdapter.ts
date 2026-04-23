import { agentVersionService } from '@/services/agentVersionService'
import type { GraphState } from '../utils/saveManager'

function toGraphState(payload: Record<string, unknown>): GraphState {
  return {
    graphId: (payload.graphId as string) ?? null,
    graphName: (payload.graphName as string) ?? null,
    nodes: (payload.nodes as any[]) ?? [],
    edges: (payload.edges as any[]) ?? [],
    viewport: (payload.viewport as { x: number; y: number; zoom: number }) ?? { x: 0, y: 0, zoom: 1 },
    graphStateFields: (payload.graphStateFields as any[]) ?? [],
    fallbackNodeId: (payload.fallbackNodeId as string) ?? null,
    agentId: null,
    versionId: null,
    workspaceId: null,
  }
}

export const graphDataAdapter = {
  async load(agentId: string, versionId: string, workspaceId: string): Promise<GraphState> {
    const version = await agentVersionService.get(agentId, versionId, workspaceId)
    return toGraphState(version.definition_payload)
  },

  async save(
    agentId: string,
    versionId: string,
    workspaceId: string,
    graphState: Partial<GraphState>,
  ): Promise<void> {
    await agentVersionService.update(agentId, versionId, workspaceId, {
      definition_payload: graphState,
    })
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
