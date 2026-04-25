import { agentReleaseService } from '@/services/agentReleaseService'
import { agentVersionService } from '@/services/agentVersionService'
import type { AgentRelease, RuntimeKind } from '@/types/agent-release'

export interface AgentReleaseVersion {
  id: string
  version: number
  status: string
  runtime_kind: string
  published_at: string | null
}

export const agentReleaseAdapter = {
  async publish(
    agentId: string,
    versionId: string,
    workspaceId: string,
    runtimeKind: RuntimeKind = 'graph',
  ): Promise<AgentReleaseVersion> {
    await agentVersionService.freeze(agentId, versionId, workspaceId)
    try {
      const release = await agentReleaseService.publish(agentId, workspaceId, {
        agent_version_id: versionId,
        runtime_kind: runtimeKind,
      })
      return mapRelease(release)
    } catch (publishError) {
      try {
        await agentVersionService.unfreeze(agentId, versionId, workspaceId)
      } catch {
        throw new Error(
          'Publishing failed and the version could not be automatically reverted to draft. ' +
            'The version is currently frozen. Please contact support or retry publishing.',
        )
      }
      throw publishError
    }
  },

  async list(agentId: string, workspaceId: string): Promise<AgentReleaseVersion[]> {
    const releases = await agentReleaseService.list(agentId, workspaceId)
    return releases.map(mapRelease)
  },

  async activate(agentId: string, releaseId: string, workspaceId: string) {
    return agentReleaseService.activate(agentId, releaseId, workspaceId)
  },

  async retire(agentId: string, releaseId: string, workspaceId: string) {
    return agentReleaseService.retire(agentId, releaseId, workspaceId)
  },
}

function mapRelease(release: AgentRelease): AgentReleaseVersion {
  return {
    id: release.id,
    version: release.release_number,
    status: release.status,
    runtime_kind: release.runtime_kind,
    published_at: release.published_at,
  }
}
