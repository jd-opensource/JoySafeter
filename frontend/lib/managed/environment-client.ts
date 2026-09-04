import { managedGet } from '@/lib/api-client'
import { apiCollectionPath, apiResourcePath } from '@/lib/managed/api-paths'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import { parseEnvironmentId, type EnvironmentId } from '@/types/entity-id'
import type { Environment } from '@/types/managed'

import { collectManagedCursorPages, parseManagedCursorPage } from './cursor-page'
import { parseEnvironmentResponse } from './environment-response-parsers'
import type { ManagedCursorPage } from './cursor-page'

const ENVIRONMENT_OPTION_PAGE_SIZE = 100

export interface ManagedEnvironmentPageRequest {
  limit?: number
  afterId?: EnvironmentId
  includeArchived?: boolean
}

export const MANAGED_ENVIRONMENTS_QUERY_ROOT = 'environments'
export const MANAGED_ENVIRONMENTS_SOURCE_KEY = 'managed-environment-list'

export function managedEnvironmentListQueryPrefix(scopeKey: string) {
  return [MANAGED_ENVIRONMENTS_QUERY_ROOT, scopeKey, MANAGED_ENVIRONMENTS_SOURCE_KEY] as const
}

export function managedEnvironmentOptionsQueryKey(scopeKey: string) {
  return ['environments', scopeKey, 'options', false] as const
}

export function managedEnvironmentQueryKey(scopeKey: string, environmentId: EnvironmentId | null) {
  return ['environment', scopeKey, environmentId] as const
}

export async function fetchManagedEnvironment(
  environmentId: EnvironmentId,
  requestScope: ManagedRequestScope,
): Promise<Environment> {
  const response = await managedGet<unknown>(
    apiResourcePath('environments', environmentId),
    managedRequestOptions(requestScope),
  )
  return parseEnvironmentResponse(response)
}

export async function fetchManagedEnvironments(
  request: ManagedEnvironmentPageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedCursorPage<Environment, EnvironmentId>> {
  const response = await managedGet<unknown>(
    apiCollectionPath('environments', {
      limit: request.limit,
      after_id: request.afterId,
      include_archived: request.includeArchived,
    }),
    managedRequestOptions(requestScope),
  )
  return parseManagedCursorPage(response, {
    parseItem: parseEnvironmentResponse,
    parseCursor: parseEnvironmentId,
    responseName: 'Environment list response',
  })
}

export async function fetchManagedEnvironmentOptions(
  requestScope: ManagedRequestScope,
): Promise<Environment[]> {
  const environments = await collectManagedCursorPages<Environment, EnvironmentId>({
    responseName: 'Environment options pagination',
    fetchPage: (afterId) =>
      fetchManagedEnvironments(
        {
          limit: ENVIRONMENT_OPTION_PAGE_SIZE,
          afterId,
          includeArchived: false,
        },
        requestScope,
      ),
  })

  return environments.filter((environment) => !environment.archived_at)
}
