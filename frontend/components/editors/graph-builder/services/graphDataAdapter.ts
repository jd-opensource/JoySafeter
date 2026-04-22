import { agentVersionService } from '@/services/agentVersionService'
import type { GraphState } from '../utils/saveManager'

export const graphDataAdapter = {
  async load(agentId: string, versionId: string, workspaceId: string): Promise<GraphState> {
    const version = await agentVersionService.get(agentId, versionId, workspaceId)
    return version.definition_payload as GraphState
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
