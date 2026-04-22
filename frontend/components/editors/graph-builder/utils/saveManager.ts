/**
 * SaveManager - Pure save executor for AgentGraph
 *
 * Responsible only for: debouncing, HTTP execution, error handling.
 * Does NOT decide whether to save (caller's responsibility).
 * Does NOT maintain hash state (store's responsibility).
 */

import type { Node, Edge } from 'reactflow'

import type { StateField } from '../types/graph'
import { computeGraphStateHash } from '@/lib/utils/graphStateHash'

import { agentService } from '../services/agentService'
import { graphDataAdapter } from '../services/graphDataAdapter'

export type SaveSource = 'manual' | 'auto' | 'debounce'

export interface GraphState {
  graphId: string | null
  graphName: string | null
  agentId?: string | null
  versionId?: string | null
  workspaceId?: string | null
  nodes: Node[]
  edges: Edge[]
  viewport?: { x: number; y: number; zoom: number }
  graphStateFields?: StateField[]
  fallbackNodeId?: string | null
}

export interface SaveManagerCallbacks {
  onSaveSuccess: (hash: string, savedGraphId: string) => void
  onSaveError: (error: string) => void
}

export class SaveManager {
  private debounceTimer: NodeJS.Timeout | null = null
  private saveRetryCount = 0
  private readonly maxRetries = 3

  constructor(
    private getState: () => GraphState,
    private callbacks: SaveManagerCallbacks,
  ) {}

  async save(source: SaveSource): Promise<void> {
    const state = this.getState()

    // Must have either agentId+versionId+workspaceId (new path) or graphId (legacy path)
    const hasNewPath = !!(state.agentId && state.versionId && state.workspaceId)
    if (!hasNewPath && !state.graphId) return

    if (typeof navigator !== 'undefined' && !navigator.onLine) {
      this.callbacks.onSaveError('offline')
      return
    }

    try {
      const seenEdges = new Set<string>()
      const deduplicatedEdges = state.edges.filter((edge) => {
        const key = `${edge.source}-${edge.target}`
        if (seenEdges.has(key)) return false
        seenEdges.add(key)
        return true
      })

      if (hasNewPath) {
        await graphDataAdapter.save(state.agentId!, state.versionId!, state.workspaceId!, {
          nodes: state.nodes,
          edges: deduplicatedEdges,
          viewport: state.viewport,
          graphStateFields: state.graphStateFields,
          fallbackNodeId: state.fallbackNodeId,
        })
      } else {
        // Legacy path: backward-compat for old workspace routes that only have graphId
        await agentService.saveGraphState({
          graphId: state.graphId!,
          nodes: state.nodes,
          edges: deduplicatedEdges,
          viewport: state.viewport,
          variables: {
            state_fields: state.graphStateFields,
            ...(state.fallbackNodeId != null && state.fallbackNodeId !== ''
              ? { fallback_node_id: state.fallbackNodeId }
              : {}),
          },
        })
      }

      const savedHash = computeGraphStateHash(
        state.nodes,
        state.edges,
        state.graphStateFields,
        state.fallbackNodeId,
      )
      this.saveRetryCount = 0
      // Use agentId as the saved ID for new path, otherwise fall back to graphId
      const savedId = state.agentId ?? state.graphId!
      this.callbacks.onSaveSuccess(savedHash, savedId)
    } catch (error) {
      this.handleSaveError(error, source)
    }
  }

  debouncedSave(delay = 2000): void {
    if (this.debounceTimer) clearTimeout(this.debounceTimer)
    this.debounceTimer = setTimeout(() => {
      this.save('debounce')
      this.debounceTimer = null
    }, delay)
  }

  async immediateSave(): Promise<void> {
    await this.save('auto')
  }

  stopAll(): void {
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer)
      this.debounceTimer = null
    }
  }

  private handleSaveError(error: unknown, source: SaveSource): void {
    const errorMessage = error instanceof Error ? error.message : 'Unknown error'
    if (this.saveRetryCount < this.maxRetries) {
      const delay = Math.pow(2, this.saveRetryCount) * 1000
      setTimeout(() => {
        const s = this.getState()
        const canRetry = (s.agentId && s.versionId && s.workspaceId) || s.graphId
        if (canRetry) this.save(source)
      }, delay)
      this.saveRetryCount++
      this.callbacks.onSaveError(errorMessage)
    } else {
      this.callbacks.onSaveError(`Save failed after ${this.maxRetries} retries: ${errorMessage}`)
    }
  }
}
