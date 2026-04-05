/**
 * SaveManager - Pure save executor for AgentGraph
 *
 * Responsible only for: debouncing, HTTP execution, error handling.
 * Does NOT decide whether to save (caller's responsibility).
 * Does NOT maintain hash state (store's responsibility).
 */

import type { Node, Edge } from 'reactflow'

import type { StateField } from '@/app/workspace/[workspaceId]/[agentId]/types/graph'
import { computeGraphStateHash } from '@/utils/graphStateHash'

import { agentService } from '../services/agentService'

export type SaveSource = 'manual' | 'auto' | 'debounce'

export interface GraphState {
  graphId: string | null
  graphName: string | null
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

    if (!state.graphId) return

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

      await agentService.saveGraphState({
        graphId: state.graphId,
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

      const savedHash = computeGraphStateHash(
        state.nodes,
        state.edges,
        state.graphStateFields,
        state.fallbackNodeId,
      )
      this.saveRetryCount = 0
      this.callbacks.onSaveSuccess(savedHash, state.graphId)
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
        if (this.getState().graphId) this.save(source)
      }, delay)
      this.saveRetryCount++
      this.callbacks.onSaveError(errorMessage)
    } else {
      this.callbacks.onSaveError(`Save failed after ${this.maxRetries} retries: ${errorMessage}`)
    }
  }
}
