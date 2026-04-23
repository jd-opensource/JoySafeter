import { agentReleaseService } from '@/services/agentReleaseService'
import type { AgentRelease } from '@/types/agent-release'
import { agentVersionService } from '@/services/agentVersionService'

export interface DeploymentVersion {
  id: string
  version: number
  status: string
  runtime_kind: string
  published_at: string | null
}

export const deploymentAdapter = {
  async deploy(agentId: string, versionId: string, workspaceId: string): Promise<DeploymentVersion> {
    await agentVersionService.freeze(agentId, versionId, workspaceId)
    try {
      const release = await agentReleaseService.publish(agentId, workspaceId, {
        agent_version_id: versionId,
        runtime_kind: 'graph',
      })
      return mapRelease(release)
    } catch (publishError) {
      // Freeze succeeded but publish failed — attempt to revert the version
      // back to draft so it remains editable. If the unfreeze also fails we
      // surface a clear message so the user knows what happened.
      try {
        await agentVersionService.unfreeze(agentId, versionId, workspaceId)
      } catch {
        throw new Error(
          'Deployment failed and the version could not be automatically reverted to draft. ' +
            'The version is currently frozen. Please contact support or retry deployment.',
        )
      }
      throw publishError
    }
  },

  async list(agentId: string, workspaceId: string): Promise<DeploymentVersion[]> {
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

function mapRelease(r: AgentRelease): DeploymentVersion {
  return {
    id: r.id,
    version: r.release_number,
    status: r.status,
    runtime_kind: r.runtime_kind,
    published_at: r.published_at,
  }
}
