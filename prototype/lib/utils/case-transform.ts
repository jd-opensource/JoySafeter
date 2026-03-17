/**
 * Universal case conversion utilities
 *
 * Used for converting between frontend camelCase and backend snake_case
 */

/**
 * Convert string from snake_case to camelCase
 */
export function snakeToCamelString(str: string): string {
  return str.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase())
}

/**
 * Convert string from camelCase to snake_case
 */
export function camelToSnakeString(str: string): string {
  return str.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)
}

/**
 * Recursively convert all object keys from snake_case to camelCase
 *
 * @example
 * ```ts
 * const input = { user_name: 'John', user_email: 'john@example.com' }
 * const output = snakeToCamel(input)
 * // { userName: 'John', userEmail: 'john@example.com' }
 * ```
 */
export function snakeToCamel<T = Record<string, unknown>>(obj: unknown): T {
  if (obj === null || obj === undefined) {
    return obj as T
  }

  if (Array.isArray(obj)) {
    return obj.map((item) => snakeToCamel(item)) as T
  }

  if (typeof obj === 'object') {
    const result: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
      const camelKey = snakeToCamelString(key)
      result[camelKey] = snakeToCamel(value)
    }
    return result as T
  }

  return obj as T
}

/**
 * Recursively convert all object keys from camelCase to snake_case
 *
 * @example
 * ```ts
 * const input = { userName: 'John', userEmail: 'john@example.com' }
 * const output = camelToSnake(input)
 * // { user_name: 'John', user_email: 'john@example.com' }
 * ```
 */
export function camelToSnake<T = Record<string, unknown>>(obj: unknown): T {
  if (obj === null || obj === undefined) {
    return obj as T
  }

  if (Array.isArray(obj)) {
    return obj.map((item) => camelToSnake(item)) as T
  }

  if (typeof obj === 'object') {
    const result: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
      const snakeKey = camelToSnakeString(key)
      result[snakeKey] = camelToSnake(value)
    }
    return result as T
  }

  return obj as T
}

/**
 * Create a type-specific mapping function
 *
 * @example
 * ```ts
 * interface User {
 *   id: string
 *   userName: string
 *   userEmail: string
 * }
 *
 * const mapUser = createMapper<User>((data) => ({
 *   id: data.id,
 *   userName: data.user_name,
 *   userEmail: data.user_email,
 * }))
 *
 * const user = mapUser(apiResponse)
 * ```
 */
export function createMapper<T>(
  transform: (data: Record<string, any>) => T
): (data: Record<string, any>) => T {
  return transform
}
