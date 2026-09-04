'use client'

import { useQuery } from '@tanstack/react-query'

import {
  fetchManagedSkillVersionOptions,
  managedSkillVersionsQueryKey,
} from '@/lib/managed/skill-client'
import { hasManagedRequestScope, useManagedRequestScope } from '@/lib/managed/request-scope'
import type { SkillId } from '@/types/entity-id'

interface UseManagedSkillVersionsOptions {
  enabled?: boolean
  staleTime?: number
}

export function useManagedSkillVersions(
  skillId: SkillId | null,
  { enabled = true, staleTime }: UseManagedSkillVersionsOptions = {},
) {
  const managedScope = useManagedRequestScope()
  return useQuery({
    queryKey: managedSkillVersionsQueryKey(managedScope.key, skillId),
    queryFn: () => fetchManagedSkillVersionOptions(skillId!, managedScope),
    enabled: enabled && skillId !== null && hasManagedRequestScope(managedScope),
    staleTime,
  })
}
