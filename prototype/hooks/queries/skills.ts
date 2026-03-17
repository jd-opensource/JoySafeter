/**
 * Skills Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'

import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api-client'
import type { Skill } from '@/types'

import { STALE_TIME } from './constants'

// ==================== Query Keys ====================

export const skillKeys = {
  all: ['skills'] as const,
  list: (includePublic?: boolean) => [...skillKeys.all, 'list', includePublic] as const,
  public: () => [...skillKeys.all, 'public'] as const,
}

// ==================== Query Hooks ====================

export function useSkills(includePublic: boolean = true, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: skillKeys.list(includePublic),
    queryFn: async (): Promise<Skill[]> => {
      // apiGet automatically unwraps response.data, returns skill array directly
      const params = new URLSearchParams()
      if (includePublic !== undefined) {
        params.append('include_public', includePublic.toString())
      }
      const url = params.toString()
        ? `skills?${params.toString()}`
        : 'skills'
      const skills = await apiGet<Skill[]>(url)
      return skills || []
    },
    enabled: options?.enabled !== false, // 默认 true，但可以设置为 false
    retry: false,
    staleTime: STALE_TIME.STANDARD,
    placeholderData: keepPreviousData,
  })
}

/**
 * Hook to get only public skills (for marketplace/store)
 * This hook reuses the data from useSkills(true) and filters client-side
 * to avoid duplicate requests while maintaining semantic clarity
 */
export function usePublicSkills(options?: { enabled?: boolean }) {
  // Reuse the same query as useSkills(true) to share cache
  const { data: allSkills = [], isLoading, error, ...rest } = useSkills(true, options)

  // Filter to only public skills using useMemo
  const publicSkills = useMemo(() => {
    return allSkills.filter(s => s.is_public)
  }, [allSkills])

  return {
    data: publicSkills,
    isLoading,
    error,
    ...rest,
  }
}

/**
 * Hook to get only user's own skills (for "My Skills" page)
 * Calls API with include_public=false to get only user-owned skills
 */
export function useMySkills(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: skillKeys.list(false), // include_public=false
    queryFn: async (): Promise<Skill[]> => {
      const params = new URLSearchParams()
      params.append('include_public', 'false')
      const skills = await apiGet<Skill[]>(`skills?${params.toString()}`)
      return skills || []
    },
    enabled: options?.enabled !== false,
    retry: false,
    staleTime: STALE_TIME.STANDARD,
    placeholderData: keepPreviousData,
  })
}

// ==================== Mutation Hooks ====================

export function useCreateSkill() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (skillData: any) => {
      const data = await apiPost<Skill>('skills', skillData)
      return data
    },
    onSuccess: () => {
      // Invalidate both "all skills" and "my skills" queries
      queryClient.invalidateQueries({ queryKey: skillKeys.all })
    },
  })
}

export function useUpdateSkill() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ id, ...updates }: { id: string; [key: string]: any }) => {
      const data = await apiPut<Skill>(`skills/${id}`, updates)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillKeys.all })
    },
  })
}

export function useDeleteSkill() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (id: string) => {
      await apiDelete(`skills/${id}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillKeys.all })
    },
  })
}
