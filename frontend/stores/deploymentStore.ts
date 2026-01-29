/**
 * Graph Deployment Status Store
 *
 * Architecture description:
 * - Zustand is only used for managing UI state (isDeploying, isUndeploying, etc.)
 * - Server data (deploymentStatus, versions) is obtained through React Query hooks
 * - This leverages React Query's caching and deduplication mechanisms
 *
 * Recommended usage:
 * - Use useDeploymentStatus(graphId) to get deployment status (from hooks/queries/graphs.ts)
 * - Use useDeploymentVersions(graphId) to get version history
 * - Use useDeploymentActions() to get deploy/undeploy operations
 */
import { create } from 'zustand'

import { graphDeploymentService, GraphDeployResponse } from '@/services/graphDeploymentService'

// ============================================================================
// Types
// ============================================================================

interface DeploymentUIState {
  // UI state
  isDeploying: boolean
  isUndeploying: boolean
  isReverting: boolean
  isRenaming: boolean
  isDeleting: boolean

  // Current operation graphId (for preventing concurrent operations)
  activeGraphId: string | null
}

interface DeploymentActions {
  // Deployment operations
  deploy: (graphId: string, name?: string) => Promise<GraphDeployResponse>
  undeploy: (graphId: string) => Promise<void>
  revertToVersion: (graphId: string, version: number) => Promise<void>
  renameVersion: (graphId: string, version: number, name: string) => Promise<void>
  deleteVersion: (graphId: string, version: number) => Promise<void>

  // Reset state
  reset: () => void
}

type DeploymentStore = DeploymentUIState & DeploymentActions

// ============================================================================
// Initial State
// ============================================================================

const initialState: DeploymentUIState = {
  isDeploying: false,
  isUndeploying: false,
  isReverting: false,
  isRenaming: false,
  isDeleting: false,
  activeGraphId: null,
}

// ============================================================================
// Store
// ============================================================================

/**
 * Deployment UI State Store
 *
 * Note: This store no longer stores server data (deploymentStatus, versions)
 * Please use React Query hooks to get this data:
 * - useDeploymentStatus(graphId)
 * - useDeploymentVersions(graphId)
 */
export const useDeploymentStore = create<DeploymentStore>((set, get) => ({
  ...initialState,

  deploy: async (graphId: string, name?: string) => {
    set({ isDeploying: true, activeGraphId: graphId })
    try {
      const result = await graphDeploymentService.deploy(graphId, name)
      return result
    } catch (error) {
      console.error('Failed to deploy:', error)
      throw error
    } finally {
      set({ isDeploying: false, activeGraphId: null })
    }
  },

  undeploy: async (graphId: string) => {
    set({ isUndeploying: true, activeGraphId: graphId })
    try {
      await graphDeploymentService.undeploy(graphId)
    } catch (error) {
      console.error('Failed to undeploy:', error)
      throw error
    } finally {
      set({ isUndeploying: false, activeGraphId: null })
    }
  },

  revertToVersion: async (graphId: string, version: number) => {
    set({ isReverting: true, activeGraphId: graphId })
    try {
      await graphDeploymentService.revertToVersion(graphId, version)
    } catch (error) {
      console.error('Failed to revert version:', error)
      throw error
    } finally {
      set({ isReverting: false, activeGraphId: null })
    }
  },

  renameVersion: async (graphId: string, version: number, name: string) => {
    set({ isRenaming: true, activeGraphId: graphId })
    try {
      await graphDeploymentService.renameVersion(graphId, version, name)
    } catch (error) {
      console.error('Failed to rename version:', error)
      throw error
    } finally {
      set({ isRenaming: false, activeGraphId: null })
    }
  },

  deleteVersion: async (graphId: string, version: number) => {
    set({ isDeleting: true, activeGraphId: graphId })
    try {
      await graphDeploymentService.deleteVersion(graphId, version)
    } catch (error) {
      console.error('Failed to delete version:', error)
      throw error
    } finally {
      set({ isDeleting: false, activeGraphId: null })
    }
  },

  reset: () => {
    set(initialState)
  },
}))

// ============================================================================
// Compatibility exports (used during gradual migration)
// ============================================================================

/**
 * @deprecated Please use useDeploymentStatus in hooks/queries/graphs.ts
 *
 * This function is kept for backward compatibility but is no longer recommended
 * because it cannot leverage React Query's deduplication mechanism
 */
export const fetchDeploymentStatusLegacy = async (graphId: string) => {
  return graphDeploymentService.getDeploymentStatus(graphId)
}
