/**
 * Memories Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
'use client'

import { keepPreviousData, useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

import { apiGet, apiPost, apiPatch, apiDelete, API_BASE } from '@/lib/api-client'

import { STALE_TIME } from './constants'

// Types
export interface UserMemory {
  memory_id: string
  memory: string
  topics?: string[]
  user_id?: string
  agent_id?: string
  team_id?: string
  input?: string
  feedback?: string
  updated_at?: string
  created_at?: string
}

export interface PaginationMeta {
  page: number
  limit: number
  total_count: number
  total_pages: number
}

export interface MemoriesResponse {
  data: UserMemory[]
  meta: PaginationMeta
}

export interface MemoryCreateRequest {
  memory: string
  topics?: string[]
}

export interface MemoryUpdateRequest {
  memory: string
  topics?: string[]
}

export interface OptimizeMemoriesResponse {
  memories: UserMemory[]
  memories_before: number
  memories_after: number
  tokens_before: number
  tokens_after: number
  tokens_saved: number
  reduction_percentage: number
}

// API endpoints
const MEMORY_API = `${API_BASE}/memory`

// Query keys
export const memoryKeys = {
  all: ['memories'] as const,
  list: (params?: MemoryQueryParams) => [...memoryKeys.all, 'list', params] as const,
  detail: (id: string) => [...memoryKeys.all, 'detail', id] as const,
  topics: () => [...memoryKeys.all, 'topics'] as const,
}

export interface MemoryQueryParams {
  page?: number
  limit?: number
  agent_id?: string
  team_id?: string
  topics?: string[]
  search_content?: string
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

// Hooks

/**
 * Fetch paginated memories list
 */
export function useMemories(params: MemoryQueryParams = {}) {
  const { page = 1, limit = 20, search_content, topics, agent_id, sort_by = 'updated_at', sort_order = 'desc' } = params

  const queryParams = new URLSearchParams()
  queryParams.set('page', page.toString())
  queryParams.set('limit', limit.toString())
  queryParams.set('sort_by', sort_by)
  queryParams.set('sort_order', sort_order)
  if (search_content) queryParams.set('search_content', search_content)
  if (topics?.length) queryParams.set('topics', topics.join(','))
  if (agent_id) queryParams.set('agent_id', agent_id)

  return useQuery<MemoriesResponse>({
    queryKey: memoryKeys.list(params),
    queryFn: () => apiGet<MemoriesResponse>(`${MEMORY_API}/memories?${queryParams.toString()}`),
    staleTime: STALE_TIME.STANDARD,
    placeholderData: keepPreviousData,
  })
}

/**
 * Fetch a single memory by ID
 */
export function useMemory(memoryId: string) {
  return useQuery<UserMemory>({
    queryKey: memoryKeys.detail(memoryId),
    queryFn: () => apiGet<UserMemory>(`${MEMORY_API}/memories/${memoryId}`),
    enabled: !!memoryId,
    staleTime: STALE_TIME.STANDARD,
  })
}

/**
 * Fetch all unique memory topics
 */
export function useMemoryTopics() {
  return useQuery<string[]>({
    queryKey: memoryKeys.topics(),
    queryFn: () => apiGet<string[]>(`${MEMORY_API}/memory_topics`),
    staleTime: STALE_TIME.STANDARD,
    placeholderData: keepPreviousData,
  })
}

/**
 * Create a new memory
 */
export function useCreateMemory() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: MemoryCreateRequest) => 
      apiPost<UserMemory>(`${MEMORY_API}/memories`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: memoryKeys.all })
    },
  })
}

/**
 * Update an existing memory
 */
export function useUpdateMemory() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ memoryId, data }: { memoryId: string; data: MemoryUpdateRequest }) =>
      apiPatch<UserMemory>(`${MEMORY_API}/memories/${memoryId}`, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: memoryKeys.all })
      queryClient.invalidateQueries({ queryKey: memoryKeys.detail(variables.memoryId) })
    },
  })
}

/**
 * Delete a single memory
 */
export function useDeleteMemory() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (memoryId: string) => 
      apiDelete<void>(`${MEMORY_API}/memories/${memoryId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: memoryKeys.all })
    },
  })
}

/**
 * Delete multiple memories
 */
export function useDeleteMemories() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (memoryIds: string[]) =>
      apiDelete<void>(`${MEMORY_API}/memories`, { body: { memory_ids: memoryIds } } as any),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: memoryKeys.all })
    },
  })
}

/**
 * Optimize memories using AI summarization
 */
export function useOptimizeMemories() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (apply: boolean = true) =>
      apiPost<OptimizeMemoriesResponse>(`${MEMORY_API}/optimize-memories`, { apply }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: memoryKeys.all })
    },
  })
}

