import { managedGet } from '@/lib/api-client'
import { apiCollectionPath, apiResourcePath, apiResourceSubpath } from '@/lib/managed/api-paths'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import { parseCredentialGroupId, type CredentialGroupId } from '@/types/entity-id'
import type { CredentialGroup, CredentialGroupCredential } from '@/types/managed'

import {
  parseCredentialGroupCredentialListResponse,
  parseCredentialGroupResponse,
} from './credential-group-response-parsers'
import {
  collectManagedCursorPages,
  parseManagedCursorPage,
  type ManagedCursorPage,
} from './cursor-page'

const CREDENTIAL_GROUP_OPTION_PAGE_SIZE = 100

export interface ManagedCredentialGroupPageRequest {
  limit?: number
  afterId?: CredentialGroupId
  includeArchived?: boolean
}

export const MANAGED_CREDENTIAL_GROUPS_QUERY_ROOT = 'credential-groups'
export const MANAGED_CREDENTIAL_GROUPS_SOURCE_KEY = 'managed-credential-group-list'

export function managedCredentialGroupOptionsQueryKey(scopeKey: string) {
  return [MANAGED_CREDENTIAL_GROUPS_QUERY_ROOT, scopeKey, 'options', false] as const
}

export function managedCredentialGroupQueryKey(
  scopeKey: string,
  credentialGroupId: CredentialGroupId | null,
) {
  return ['credential-group', scopeKey, credentialGroupId] as const
}

export function managedCredentialGroupMembersQueryPrefix(
  scopeKey: string,
  credentialGroupId: CredentialGroupId,
) {
  return ['credential-group-members', scopeKey, credentialGroupId] as const
}

export function managedCredentialGroupMembersQueryKey(
  scopeKey: string,
  credentialGroupId: CredentialGroupId | null,
  includeArchived: boolean,
) {
  return ['credential-group-members', scopeKey, credentialGroupId, includeArchived] as const
}

export async function fetchManagedCredentialGroup(
  credentialGroupId: CredentialGroupId,
  requestScope: ManagedRequestScope,
): Promise<CredentialGroup> {
  const response = await managedGet<unknown>(
    apiResourcePath('credential-groups', credentialGroupId),
    managedRequestOptions(requestScope),
  )
  return parseCredentialGroupResponse(response)
}

export async function fetchManagedCredentialGroupMembers(
  credentialGroupId: CredentialGroupId,
  includeArchived: boolean,
  requestScope: ManagedRequestScope,
): Promise<CredentialGroupCredential[]> {
  const response = await managedGet<unknown>(
    apiResourceSubpath('credential-groups', credentialGroupId, ['members'], {
      include_archived: includeArchived,
    }),
    managedRequestOptions(requestScope),
  )
  if (!response || typeof response !== 'object' || Array.isArray(response)) {
    throw new Error('Invalid Credential Group members response')
  }
  const data = (response as { data?: unknown }).data
  if (!Array.isArray(data)) throw new Error('Invalid Credential Group members response')
  return parseCredentialGroupCredentialListResponse(data)
}

export async function fetchManagedCredentialGroups(
  request: ManagedCredentialGroupPageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedCursorPage<CredentialGroup, CredentialGroupId>> {
  const response = await managedGet<unknown>(
    apiCollectionPath('credential-groups', {
      limit: request.limit,
      after_id: request.afterId,
      include_archived: request.includeArchived,
    }),
    managedRequestOptions(requestScope),
  )
  return parseManagedCursorPage(response, {
    parseItem: parseCredentialGroupResponse,
    parseCursor: parseCredentialGroupId,
    responseName: 'Credential Group list response',
  })
}

export async function fetchManagedCredentialGroupOptions(
  requestScope: ManagedRequestScope,
): Promise<CredentialGroup[]> {
  const credentialGroups = await collectManagedCursorPages<CredentialGroup, CredentialGroupId>({
    responseName: 'Credential Group options pagination',
    fetchPage: (afterId) =>
      fetchManagedCredentialGroups(
        {
          limit: CREDENTIAL_GROUP_OPTION_PAGE_SIZE,
          afterId,
          includeArchived: false,
        },
        requestScope,
      ),
  })
  return credentialGroups.filter((credentialGroup) => !credentialGroup.archived_at)
}
