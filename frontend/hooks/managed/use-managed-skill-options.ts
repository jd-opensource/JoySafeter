'use client'

import { useQuery } from '@tanstack/react-query'

import { fetchManagedSkillOptions, managedSkillOptionsQueryKey } from '@/lib/managed/skill-client'
import { hasManagedRequestScope, useManagedRequestScope } from '@/lib/managed/request-scope'

interface UseManagedSkillOptionsOptions {
  enabled?: boolean
  refetchOnMount?: boolean | 'always'
}

export function useManagedSkillOptions({
  enabled = true,
  refetchOnMount,
}: UseManagedSkillOptionsOptions = {}) {
  const managedScope = useManagedRequestScope()
  return useQuery({
    queryKey: managedSkillOptionsQueryKey(managedScope.key),
    queryFn: () => fetchManagedSkillOptions(managedScope),
    enabled: enabled && hasManagedRequestScope(managedScope),
    refetchOnMount,
  })
}
