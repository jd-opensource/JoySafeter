import {
  agentReleaseAdapter,
  type AgentReleaseVersion,
} from '@/components/agents/agent-build/agent-release-adapter'
import type { RuntimeKind } from '@/types/agent-release'

export type DeploymentVersion = AgentReleaseVersion

export const deploymentAdapter = {
  async deploy(agentId: string, versionId: string, workspaceId: string, runtimeKind?: RuntimeKind): Promise<DeploymentVersion> {
    return agentReleaseAdapter.publish(agentId, versionId, workspaceId, runtimeKind || 'graph')
  },

  async list(agentId: string, workspaceId: string): Promise<DeploymentVersion[]> {
    return agentReleaseAdapter.list(agentId, workspaceId)
  },

  async activate(agentId: string, releaseId: string, workspaceId: string) {
    return agentReleaseAdapter.activate(agentId, releaseId, workspaceId)
  },

  async retire(agentId: string, releaseId: string, workspaceId: string) {
    return agentReleaseAdapter.retire(agentId, releaseId, workspaceId)
  },
}
