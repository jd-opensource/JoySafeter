/**
 * Shared constants for React Query hooks
 *
 * Centralized configuration for query options to ensure consistency
 * across all query hooks in the application.
 */

/**
 * Stale time constants (in milliseconds)
 *
 * Stale time determines how long data is considered fresh.
 * During this time, React Query won't refetch the data.
 */
export const STALE_TIME = {
  // Short-lived data (30 seconds) - for frequently changing data like graphs, workspaces
  SHORT: 30 * 1000,

  // Standard cache (1 minute) - most queries use this
  STANDARD: 60 * 1000,

  // Long cache (5 minutes) - for data that rarely changes
  LONG: 5 * 60 * 1000,

  // Very long cache (1 hour) - for settings and static data
  VERY_LONG: 60 * 60 * 1000,
} as const

/**
 * Cache time constants (in milliseconds)
 *
 * Cache time determines how long unused data stays in cache.
 * After this time, data is garbage collected.
 */
export const CACHE_TIME = {
  // Standard cache retention (5 minutes)
  STANDARD: 5 * 60 * 1000,

  // Long cache retention (10 minutes)
  LONG: 10 * 60 * 1000,
} as const

/**
 * Default query options
 *
 * These can be used as defaults for most queries
 */
export const DEFAULT_QUERY_OPTIONS = {
  retry: false,
  staleTime: STALE_TIME.STANDARD,
  placeholderData: undefined, // Use keepPreviousData explicitly when needed
} as const
