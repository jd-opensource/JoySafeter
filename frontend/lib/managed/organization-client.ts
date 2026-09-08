import { managedDelete, managedGet, managedPost, managedPut } from '@/lib/api-client'
import { apiCollectionPath, apiResourcePath, apiResourceSubpath } from '@/lib/managed/api-paths'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import {
  parseOrganizationId,
  parseOrganizationMemberId,
  type OrganizationId,
  type OrganizationMemberId,
  type UserId,
} from '@/types/entity-id'
import type { OrgInfo } from '@/stores/managed/project-store'

import {
  collectManagedCursorPages,
  parseManagedCursorPage,
  type ManagedCursorPage,
} from './cursor-page'
import {
  parseOrganizationListItemResponse,
  parseMemberCandidateListResponse,
  parseOrganizationCreateResponse,
  parseOrganizationDetailResponse,
  parseOrganizationMemberResponse,
  parseOrganizationOwnershipTransferResponse,
  parseOrganizationUpdateResponse,
  parsePlatformOrganizationResponse,
  type MemberCandidate,
  type OrganizationCreateResult,
  type OrganizationDetail,
  type OrganizationMemberRecord,
  type OrganizationOwnershipTransferResult,
  type OrganizationUpdateResult,
  type PlatformOrganization,
} from './tenant-response-parsers'

const PLATFORM_ORGANIZATION_PAGE_SIZE = 500
const ORGANIZATION_MEMBER_OPTION_PAGE_SIZE = 200

export interface ManagedOrganizationPageRequest {
  limit?: number
  afterId?: OrganizationId
  search?: string
}

export interface ManagedOrganizationMemberPageRequest {
  limit?: number
  afterId?: OrganizationMemberId
  search?: string
}

export interface ManagedOrganizationCreateInput {
  name: string
  slug?: string
}

export interface ManagedOrganizationUpdateInput {
  name?: string
  logo?: string
  projectCreationPolicy?: 'admins_only' | 'all_members'
}

export interface ManagedOrganizationMemberInput {
  email: string
  role: string
}

export const MANAGED_ORGANIZATIONS_QUERY_ROOT = 'organizations'
export const MANAGED_ORGANIZATIONS_SOURCE_KEY = 'managed-organization-list'
export const MANAGED_PLATFORM_ORGANIZATIONS_QUERY_ROOT = 'platform-organizations'
export const MANAGED_ORGANIZATION_MEMBERS_QUERY_ROOT = 'organization-members'
export const MANAGED_ORGANIZATION_MEMBERS_SOURCE_KEY = 'managed-organization-member-list'

export function managedOrganizationQueryKey(organizationId: OrganizationId | null) {
  return ['organization-detail', organizationId] as const
}

export function managedOrganizationMemberOptionsQueryKey(organizationId: OrganizationId | null) {
  return [...managedOrganizationMembersQueryPrefix(organizationId), 'options'] as const
}

export function managedOrganizationMembersQueryPrefix(organizationId: OrganizationId | null) {
  return [MANAGED_ORGANIZATION_MEMBERS_QUERY_ROOT, organizationId] as const
}

export function managedPlatformOrganizationsQueryKey() {
  return [MANAGED_PLATFORM_ORGANIZATIONS_QUERY_ROOT] as const
}

export async function fetchManagedOrganization(
  organizationId: OrganizationId,
): Promise<OrganizationDetail> {
  const response = await managedGet<unknown>(apiResourcePath('organizations', organizationId))
  return parseOrganizationDetailResponse(response)
}

export async function createManagedOrganization(
  input: ManagedOrganizationCreateInput,
): Promise<OrganizationCreateResult> {
  const response = await managedPost<unknown>(apiCollectionPath('organizations'), {
    name: input.name,
    ...(input.slug ? { slug: input.slug } : {}),
  })
  return parseOrganizationCreateResponse(response)
}

export async function updateManagedOrganization(
  organizationId: OrganizationId,
  input: ManagedOrganizationUpdateInput,
): Promise<OrganizationUpdateResult> {
  const response = await managedPut<unknown>(apiResourcePath('organizations', organizationId), {
    ...(input.name !== undefined ? { name: input.name } : {}),
    ...(input.logo !== undefined ? { logo: input.logo } : {}),
    ...(input.projectCreationPolicy !== undefined
      ? { project_creation_policy: input.projectCreationPolicy }
      : {}),
  })
  return parseOrganizationUpdateResponse(response)
}

export async function deleteManagedOrganization(organizationId: OrganizationId): Promise<void> {
  await managedDelete<void>(apiResourcePath('organizations', organizationId))
}

export async function transferManagedOrganizationOwnership(
  organizationId: OrganizationId,
  newOwnerUserId: UserId,
): Promise<OrganizationOwnershipTransferResult> {
  const response = await managedPost<unknown>(
    apiResourcePath('organizations', organizationId, 'transfer-ownership'),
    { new_owner_user_id: newOwnerUserId },
  )
  return parseOrganizationOwnershipTransferResponse(response)
}

export async function fetchManagedOrganizations(
  request: ManagedOrganizationPageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedCursorPage<OrgInfo, OrganizationId>> {
  const response = await managedGet<unknown>(
    apiCollectionPath('organizations', {
      q: request.search || undefined,
      limit: request.limit,
      after_id: request.afterId,
    }),
    managedRequestOptions(requestScope),
  )
  return parseManagedCursorPage(response, {
    parseItem: parseOrganizationListItemResponse,
    parseCursor: parseOrganizationId,
    responseName: 'Organization list response',
  })
}

export async function fetchManagedOrganizationMembers(
  request: ManagedOrganizationMemberPageRequest,
  organizationId: OrganizationId,
): Promise<ManagedCursorPage<OrganizationMemberRecord, OrganizationMemberId>> {
  const response = await managedGet<unknown>(
    apiResourceSubpath('organizations', organizationId, ['members'], {
      q: request.search || undefined,
      limit: request.limit,
      after_id: request.afterId,
    }),
  )
  return parseManagedCursorPage(response, {
    parseItem: parseOrganizationMemberResponse,
    parseCursor: parseOrganizationMemberId,
    responseName: 'Organization member list response',
  })
}

export async function searchManagedOrganizationMemberCandidates(
  organizationId: OrganizationId,
  search: string,
  limit = 10,
): Promise<MemberCandidate[]> {
  const response = await managedGet<unknown>(
    apiResourceSubpath('organizations', organizationId, ['member-candidates'], {
      q: search,
      limit,
    }),
  )
  return parseMemberCandidateListResponse(response)
}

export async function addManagedOrganizationMember(
  organizationId: OrganizationId,
  input: ManagedOrganizationMemberInput,
): Promise<OrganizationMemberRecord> {
  const response = await managedPost<unknown>(
    apiResourcePath('organizations', organizationId, 'members'),
    input,
  )
  return parseOrganizationMemberResponse(response)
}

export async function updateManagedOrganizationMemberRole(
  organizationId: OrganizationId,
  userId: UserId,
  role: string,
): Promise<OrganizationMemberRecord> {
  const response = await managedPut<unknown>(
    apiResourcePath('organizations', organizationId, 'members', userId),
    { role },
  )
  return parseOrganizationMemberResponse(response)
}

export async function removeManagedOrganizationMember(
  organizationId: OrganizationId,
  userId: UserId,
): Promise<void> {
  await managedDelete<void>(apiResourcePath('organizations', organizationId, 'members', userId))
}

export async function fetchManagedOrganizationMemberOptions(
  organizationId: OrganizationId,
): Promise<OrganizationMemberRecord[]> {
  return collectManagedCursorPages<OrganizationMemberRecord, OrganizationMemberId>({
    responseName: 'Organization member options pagination',
    fetchPage: (afterId) =>
      fetchManagedOrganizationMembers(
        { limit: ORGANIZATION_MEMBER_OPTION_PAGE_SIZE, afterId },
        organizationId,
      ),
  })
}

export async function fetchManagedPlatformOrganizations(
  requestScope: ManagedRequestScope,
): Promise<PlatformOrganization[]> {
  return collectManagedCursorPages<PlatformOrganization, OrganizationId>({
    responseName: 'Platform Organization pagination',
    fetchPage: (afterId) =>
      fetchManagedPlatformOrganizationPage(
        { limit: PLATFORM_ORGANIZATION_PAGE_SIZE, afterId },
        requestScope,
      ),
  })
}

export async function fetchManagedPlatformOrganizationPage(
  request: Pick<ManagedOrganizationPageRequest, 'limit' | 'afterId'>,
  requestScope: ManagedRequestScope,
): Promise<ManagedCursorPage<PlatformOrganization, OrganizationId>> {
  const response = await managedGet<unknown>(
    apiCollectionPath('auth/platform/organizations', {
      limit: request.limit,
      after_id: request.afterId,
    }),
    managedRequestOptions(requestScope),
  )
  return parseManagedCursorPage(response, {
    parseItem: parsePlatformOrganizationResponse,
    parseCursor: parseOrganizationId,
    responseName: 'Platform Organization list response',
  })
}
