/**
 * SaveManager - Unified save management for AgentGraph
 * 
 * Centralizes all save logic including:
 * - Manual saves
 * - Auto-saves (debounced)
 * - Error handling and retry logic
 */

import type { Node, Edge } from 'reactflow'

import { computeGraphStateHash } from '@/utils/graphStateHash'

import { agentService } from '../services/agentService'

export type SaveSource = 'manual' | 'auto' | 'debounce'

export interface GraphState {
  graphId: string | null
  graphName: string | null
  nodes: Node[]
  edges: Edge[]
  viewport?: { x: number; y: number; zoom: number }
  graphVariables: Record<string, unknown>
  lastSavedStateHash?: string | null
}

export interface SaveManagerCallbacks {
  onSaveSuccess: (hash: string) => void
  onSaveError: (error: string) => void
}

export class SaveManager {
  private debounceTimer: NodeJS.Timeout | null = null
  
  private lastSavedHash: string | null = null
  private saveRetryCount = 0
  private readonly maxRetries = 3
  
  constructor(
    private getState: () => GraphState,
    private callbacks: SaveManagerCallbacks
  ) {}
  
  /**
   * Unified save entry point
   * 
   * @param source - Source of the save request
   * @param force - Force save even if hash matches (default: false)
   */
  async save(source: SaveSource, force = false): Promise<void> {
    const state = this.getState()
    
    // Check prerequisites - only graphId is required, graphName is optional
    // Backend API only needs graphId to save state
    if (!state.graphId) {
      return
    }
    
    // Check network status
    if (typeof navigator !== 'undefined' && !navigator.onLine) {
      this.callbacks.onSaveError('offline')
      return
    }
    
    // Compute current state hash
    const currentHash = computeGraphStateHash(state.nodes, state.edges)
    
    // 优先从 state 同步 hash（如果 SaveManager 的 hash 还未设置，或者 state 中的 hash 更新）
    // 这确保在每次保存时都使用最新的 hash 进行比较
    if (state.lastSavedStateHash) {
      // 如果 SaveManager 的 hash 为 null，或者 state 中的 hash 与当前不同，则更新
      if (this.lastSavedHash === null || this.lastSavedHash !== state.lastSavedStateHash) {
        this.lastSavedHash = state.lastSavedStateHash
      }
    }
    
    // Skip if hash matches (unless forced)
    // 如果 hash 匹配且不强制保存，则跳过
    if (!force && this.lastSavedHash !== null && currentHash === this.lastSavedHash) {
      return
    }
    
    try {
      // Deduplicate edges before saving
      const seenEdges = new Set<string>()
      const deduplicatedEdges = state.edges.filter(edge => {
        const key = `${edge.source}-${edge.target}`
        if (seenEdges.has(key)) {
          return false
        }
        seenEdges.add(key)
        return true
      })
      
      // Perform save
      await agentService.saveGraphState({
        graphId: state.graphId,
        nodes: state.nodes,
        edges: deduplicatedEdges,
        viewport: state.viewport,
        variables: { context: state.graphVariables },
      })
      
      // Update state on success
      this.lastSavedHash = currentHash
      this.saveRetryCount = 0
      this.callbacks.onSaveSuccess(currentHash)
    } catch (error) {
      this.handleSaveError(error, source)
    }
  }
  
  /**
   * Debounced save - triggers after delay, cancels previous pending saves
   * 
   * @param delay - Delay in milliseconds (default: 2000ms)
   */
  debouncedSave(delay = 2000): void {
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer)
    }
    
    this.debounceTimer = setTimeout(() => {
      this.save('debounce')
      this.debounceTimer = null
    }, delay)
  }
  
  /**
   * Immediate save - saves without delay
   */
  async immediateSave(): Promise<void> {
    await this.save('auto', true)
  }
  
  /**
   * Handle save errors with exponential backoff retry
   */
  private handleSaveError(error: unknown, source: SaveSource): void {
    const errorMessage = error instanceof Error ? error.message : 'Unknown error'
    
    if (this.saveRetryCount < this.maxRetries) {
      const delay = Math.pow(2, this.saveRetryCount) * 1000 // Exponential backoff
      
      setTimeout(() => {
        // Check if graphId hasn't changed before retrying
        const currentState = this.getState()
        if (currentState.graphId) {
          this.save(source, true) // Force retry
        }
      }, delay)
      
      this.saveRetryCount++
      this.callbacks.onSaveError(errorMessage)
    } else {
      this.callbacks.onSaveError(`Save failed after ${this.maxRetries} retries: ${errorMessage}`)
    }
  }
  
  /**
   * Stop all save timers
   */
  stopAll(): void {
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer)
      this.debounceTimer = null
    }
  }
  
  /**
   * Get current save state
   */
  getSaveState(): {
    lastSavedHash: string | null
    saveRetryCount: number
    hasActiveTimers: boolean
  } {
    return {
      lastSavedHash: this.lastSavedHash,
      saveRetryCount: this.saveRetryCount,
      hasActiveTimers: !!this.debounceTimer,
    }
  }
  
  /**
   * Set last saved hash (used when loading initial state)
   */
  setLastSavedHash(hash: string | null): void {
    this.lastSavedHash = hash
  }
}
