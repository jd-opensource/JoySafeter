import { agentVersionService } from '@/services/agentVersionService'

export async function findOrCreateGraphByTemplate(
  _templateName: string,
  _templateSlug: string,
  workspaceId: string,
  agentId?: string,
): Promise<{ id: string; nodes?: unknown[]; edges?: unknown[]; variables?: Record<string, unknown> }> {
  if (!agentId) {
    throw new Error('agentId is required to find or create a graph version')
  }

  // In the new model, "finding a graph" means getting the current draft version
  const versions = await agentVersionService.list(agentId, workspaceId)
  const draft = versions.find((v) => v.status === 'draft' && v.definition_kind === 'graph')
  if (draft) {
    const payload = (draft.definition_payload as Record<string, unknown>) || {}
    return { id: draft.id, ...payload }
  }

  // Create a new graph version from template
  const newVersion = await agentVersionService.create(agentId, workspaceId, {
    definition_kind: 'graph',
    definition_payload: { nodes: [], edges: [], variables: {} },
  })
  const payload = (newVersion.definition_payload as Record<string, unknown>) || {}
  return { id: newVersion.id, ...payload }
}
