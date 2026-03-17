/**
 * Graph deployment version service
 */
import { apiGet, apiPost, apiDelete, apiPatch, API_BASE } from '@/lib/api-client'

export interface GraphDeploymentVersion {
  id: string
  version: number
  name?: string | null
  isActive: boolean
  createdAt: string
  createdBy?: string | null
  createdByName?: string | null  // Creator username
}

export interface GraphVersionState {
  nodes: Array<{
    id: string
    type: string
    position: { x: number; y: number }
    positionAbsolute?: { x: number; y: number }
    data: Record<string, unknown>
    width?: number
    height?: number
  }>
  edges: Array<{
    id: string
    source: string
    target: string
  }>
  variables?: Record<string, unknown>
}

export interface GraphDeploymentVersionWithState extends GraphDeploymentVersion {
  state: GraphVersionState
}

export interface GraphDeploymentStatus {
  isDeployed: boolean
  deployedAt: string | null
  deployment: GraphDeploymentVersion | null
  needsRedeployment: boolean
}

export interface GraphDeployResponse {
  success: boolean
  message: string
  version: number
  isActive: boolean
  needsRedeployment: boolean
}

export interface GraphDeploymentVersionsResponse {
  versions: GraphDeploymentVersion[]
  total: number
  page: number
  pageSize: number
  totalPages: number
}

class GraphDeploymentService {
  private getBaseUrl(graphId: string) {
    return `${API_BASE}/graphs/${graphId}`
  }

  /**
   * Get deployment status
   */
  async getDeploymentStatus(graphId: string): Promise<GraphDeploymentStatus> {
    return apiGet<GraphDeploymentStatus>(`${this.getBaseUrl(graphId)}/deploy`)
  }

  /**
   * Deploy graph
   */
  async deploy(graphId: string, name?: string): Promise<GraphDeployResponse> {
    return apiPost<GraphDeployResponse>(`${this.getBaseUrl(graphId)}/deploy`, { name })
  }

  /**
   * Undeploy graph
   */
  async undeploy(graphId: string): Promise<{ isDeployed: boolean; deployedAt: null }> {
    return apiDelete<{ isDeployed: boolean; deployedAt: null }>(`${this.getBaseUrl(graphId)}/deploy`)
  }

  /**
   * Get all deployment versions (paginated)
   */
  async getVersions(graphId: string, page: number = 1, pageSize: number = 10): Promise<GraphDeploymentVersionsResponse> {
    return apiGet<GraphDeploymentVersionsResponse>(`${this.getBaseUrl(graphId)}/deployments?page=${page}&page_size=${pageSize}`)
  }

  /**
   * Get specific version
   */
  async getVersion(graphId: string, version: number): Promise<GraphDeploymentVersion> {
    return apiGet<GraphDeploymentVersion>(`${this.getBaseUrl(graphId)}/deployments/${version}`)
  }

  /**
   * Get complete state of specific version (for preview)
   */
  async getVersionState(graphId: string, version: number): Promise<GraphDeploymentVersionWithState> {
    return apiGet<GraphDeploymentVersionWithState>(`${this.getBaseUrl(graphId)}/deployments/${version}/state`)
  }

  /**
   * Rename version
   */
  async renameVersion(graphId: string, version: number, name: string): Promise<GraphDeploymentVersion> {
    return apiPatch<GraphDeploymentVersion>(`${this.getBaseUrl(graphId)}/deployments/${version}`, { name })
  }

  /**
   * Activate version
   */
  async activateVersion(graphId: string, version: number): Promise<{ success: boolean; deployedAt: string }> {
    return apiPost<{ success: boolean; deployedAt: string }>(`${this.getBaseUrl(graphId)}/deployments/${version}/activate`)
  }

  /**
   * Revert to specified version
   */
  async revertToVersion(graphId: string, version: number): Promise<{
    success: boolean
    message: string
    version: number
    isActive: boolean
  }> {
    return apiPost(`${this.getBaseUrl(graphId)}/deployments/${version}/revert`)
  }

  /**
   * Delete version
   */
  async deleteVersion(graphId: string, version: number): Promise<{ success: boolean; message: string }> {
    return apiDelete<{ success: boolean; message: string }>(`${this.getBaseUrl(graphId)}/deployments/${version}`)
  }
}

export const graphDeploymentService = new GraphDeploymentService()
