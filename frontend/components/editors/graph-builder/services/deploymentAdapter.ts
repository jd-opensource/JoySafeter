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
    const release = await agentReleaseService.publish(agentId, workspaceId, {
      agent_version_id: versionId,
      runtime_kind: 'graph',
    })
    return mapRelease(release)
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
