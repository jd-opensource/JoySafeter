import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { STALE_TIME } from './constants'
import { skillKeys } from './skills'
import { skillVersionService } from '@/services/skillVersionService'
import type { SkillVersionSummary, SkillVersion } from '@/services/skillVersionService'

export { type SkillVersionSummary, type SkillVersion } from '@/services/skillVersionService'

export const skillVersionKeys = {
  all: ['skill-versions'] as const,
  list: (skillId: string) => [...skillVersionKeys.all, 'list', skillId] as const,
  detail: (skillId: string, version: string) =>
    [...skillVersionKeys.all, 'detail', skillId, version] as const,
  latest: (skillId: string) => [...skillVersionKeys.all, 'latest', skillId] as const,
}

export function useSkillVersions(skillId: string) {
  return useQuery({
    queryKey: skillVersionKeys.list(skillId),
    queryFn: () => skillVersionService.listVersions(skillId),
    enabled: !!skillId,
    retry: false,
    staleTime: STALE_TIME.STANDARD,
  })
}

export function useSkillVersion(skillId: string, version: string) {
  return useQuery({
    queryKey: skillVersionKeys.detail(skillId, version),
    queryFn: () => skillVersionService.getVersion(skillId, version),
    enabled: !!skillId && !!version,
    retry: false,
    staleTime: STALE_TIME.STANDARD,
  })
}

export function usePublishVersion(skillId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { version: string; release_notes?: string }) =>
      skillVersionService.publishVersion(skillId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillVersionKeys.list(skillId) })
      queryClient.invalidateQueries({ queryKey: skillKeys.all })
    },
  })
}

export function useDeleteVersion(skillId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (version: string) => skillVersionService.deleteVersion(skillId, version),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillVersionKeys.list(skillId) })
    },
  })
}

export function useRestoreDraft(skillId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (version: string) =>
      skillVersionService.restoreDraft(skillId, { version }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillKeys.all })
    },
  })
}
