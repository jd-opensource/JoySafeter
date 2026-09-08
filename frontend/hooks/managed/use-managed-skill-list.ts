'use client'

import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import {
  fetchManagedSkills,
  MANAGED_SKILLS_QUERY_ROOT,
  MANAGED_SKILLS_SOURCE_KEY,
} from '@/lib/managed/skill-client'
import { parseSkillId, type SkillId } from '@/types/entity-id'
import type { SkillRecord } from '@/types/managed'

export function useManagedSkillList() {
  return usePaginatedList<SkillRecord, SkillId>({
    queryKey: MANAGED_SKILLS_QUERY_ROOT,
    sourceKey: MANAGED_SKILLS_SOURCE_KEY,
    parseCursor: parseSkillId,
    fetchPage: fetchManagedSkills,
  })
}
