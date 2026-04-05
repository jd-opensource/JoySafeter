/**
 * Execution Store Utils
 *
 * Shared utility functions
 */

/**
 * Generate a unique ID
 * @param prefix ID prefix
 * @returns unique ID string
 */
export function generateId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`
}
