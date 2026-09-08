'use client'

import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import {
  fetchManagedEnvironments,
  MANAGED_ENVIRONMENTS_QUERY_ROOT,
  MANAGED_ENVIRONMENTS_SOURCE_KEY,
} from '@/lib/managed/environment-client'
import { parseEnvironmentId, type EnvironmentId } from '@/types/entity-id'
import type { Environment } from '@/types/managed'

export function useManagedEnvironmentList(includeArchived: boolean) {
  return usePaginatedList<Environment, EnvironmentId>({
    queryKey: MANAGED_ENVIRONMENTS_QUERY_ROOT,
    sourceKey: MANAGED_ENVIRONMENTS_SOURCE_KEY,
    includeArchived,
    parseCursor: parseEnvironmentId,
    fetchPage: fetchManagedEnvironments,
  })
}
