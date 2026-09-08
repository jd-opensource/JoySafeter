'use client'

import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import {
  fetchManagedProjects,
  MANAGED_PROJECTS_QUERY_ROOT,
  MANAGED_PROJECTS_SOURCE_KEY,
} from '@/lib/managed/project-client'
import { parseProjectId, type ProjectId } from '@/types/entity-id'
import type { ProjectSummary } from '@/lib/managed/tenant-response-parsers'

export function useManagedProjectList(includeArchived: boolean) {
  return usePaginatedList<ProjectSummary, ProjectId>({
    queryKey: MANAGED_PROJECTS_QUERY_ROOT,
    sourceKey: MANAGED_PROJECTS_SOURCE_KEY,
    includeArchived,
    parseCursor: parseProjectId,
    fetchPage: fetchManagedProjects,
  })
}
