/**
 * Execution Store - compatibility layer
 *
 * Re-exports from the new modular structure.
 * Maintains backward compatibility so existing code needs no changes.
 */

export { useExecutionStore } from './execution/executionStore'
export type { InterruptInfo } from './execution/types'
