import { managedGet } from '@/lib/api-client'
import { apiCollectionPath, apiResourcePath } from '@/lib/managed/api-paths'
import {
  managedRequestOptions,
  managedScopeKey,
  type ManagedRequestScope,
} from '@/lib/managed/request-scope'
import { parseProjectId, type OrganizationId, type ProjectId } from '@/types/entity-id'

import { collectManagedCursorPages, parseManagedCursorPage } from './cursor-page'
import { parseProjectSummaryResponse, type ProjectSummary } from './tenant-response-parsers'
import type { ManagedCursorPage } from './cursor-page'

const PROJECT_OPTION_PAGE_SIZE = 200

export interface ManagedProjectPageRequest {
  limit?: number
  afterId?: ProjectId
  includeArchived?: boolean
}

export const MANAGED_PROJECTS_QUERY_ROOT = 'projects'
export const MANAGED_PROJECTS_SOURCE_KEY = 'managed-project-list'

export function managedProjectOptionsQueryKey(orgId: string | null) {
  return [MANAGED_PROJECTS_QUERY_ROOT, orgId, 'options', false] as const
}

export function managedProjectQueryKey(
  organizationId: OrganizationId | null,
  projectId: ProjectId | null,
) {
  return ['project', organizationId, projectId] as const
}

export async function fetchManagedProject(
  projectId: ProjectId,
  requestScope: ManagedRequestScope,
): Promise<ProjectSummary> {
  const response = await managedGet<unknown>(
    apiResourcePath('auth/projects', projectId),
    managedRequestOptions(requestScope),
  )
  return parseProjectSummaryResponse(response)
}

export async function fetchManagedProjects(
  request: ManagedProjectPageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedCursorPage<ProjectSummary, ProjectId>> {
  const response = await managedGet<unknown>(
    apiCollectionPath('auth/projects', {
      limit: request.limit,
      after_id: request.afterId,
      include_archived: request.includeArchived,
    }),
    managedRequestOptions(requestScope),
  )
  return parseManagedCursorPage(response, {
    parseItem: parseProjectSummaryResponse,
    parseCursor: parseProjectId,
    responseName: 'Project list response',
  })
}

export async function fetchManagedProjectOptions(
  requestScope: ManagedRequestScope,
): Promise<ProjectSummary[]> {
  return collectManagedCursorPages<ProjectSummary, ProjectId>({
    responseName: 'Project options pagination',
    fetchPage: (afterId) =>
      fetchManagedProjects(
        {
          limit: PROJECT_OPTION_PAGE_SIZE,
          afterId,
          includeArchived: false,
        },
        requestScope,
      ),
  })
}

export function fetchManagedOrganizationProjectOptions(
  organizationId: OrganizationId,
): Promise<ProjectSummary[]> {
  return fetchManagedProjectOptions({
    orgId: organizationId,
    projectId: null,
    key: managedScopeKey(organizationId, null),
  })
}
