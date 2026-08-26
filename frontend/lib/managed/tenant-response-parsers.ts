import type { OrgInfo, ProjectInfo } from '@/stores/managed/project-store'
import {
  parseOptionalId,
  parseOrganizationId,
  parseOrganizationMemberId,
  parseProjectId,
  parseUserId,
  type OrganizationId,
  type OrganizationMemberId,
  type ProjectId,
  type UserId,
} from '@/types/entity-id'

import { isRecord } from './quickstart-value-coercion'

function responseRecord(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) throw new TypeError(`Expected ${label} to be an object`)
  return value
}

function requiredString(value: Record<string, unknown>, field: string, label: string): string {
  const fieldValue = value[field]
  if (typeof fieldValue !== 'string') {
    throw new TypeError(`Expected ${label}.${field} to be a string`)
  }
  return fieldValue
}

function requiredBoolean(value: Record<string, unknown>, field: string, label: string): boolean {
  const fieldValue = value[field]
  if (typeof fieldValue !== 'boolean') {
    throw new TypeError(`Expected ${label}.${field} to be a boolean`)
  }
  return fieldValue
}

function requiredNumber(value: Record<string, unknown>, field: string, label: string): number {
  const fieldValue = value[field]
  if (typeof fieldValue !== 'number') {
    throw new TypeError(`Expected ${label}.${field} to be a number`)
  }
  return fieldValue
}

function requiredStringList(
  value: Record<string, unknown>,
  field: string,
  label: string,
): string[] {
  const fieldValue = value[field]
  if (!Array.isArray(fieldValue) || fieldValue.some((item) => typeof item !== 'string')) {
    throw new TypeError(`Expected ${label}.${field} to be a string array`)
  }
  return fieldValue
}

function optionalNullableString(
  value: Record<string, unknown>,
  field: string,
  label: string,
): string | null | undefined {
  const fieldValue = value[field]
  if (fieldValue === undefined || fieldValue === null || typeof fieldValue === 'string') {
    return fieldValue
  }
  throw new TypeError(`Expected ${label}.${field} to be a string or null`)
}

export interface OrganizationInfoPayload extends Omit<OrgInfo, 'id'> {
  id: string
}

export interface ProjectInfoPayload extends Omit<ProjectInfo, 'id' | 'org_id'> {
  id: string
  org_id?: string
}

export interface AuthContextResponsePayload {
  user: {
    id: string
    email: string
    name: string
  }
  organization: OrganizationInfoPayload
  project: ProjectInfoPayload
  organizations: OrganizationInfoPayload[]
  projects: ProjectInfoPayload[]
}

export interface AuthContextResponse {
  user: {
    id: UserId
    email: string
    name: string
  }
  organization: OrgInfo
  project: ProjectInfo
  organizations: OrgInfo[]
  projects: ProjectInfo[]
}

export interface SwitchContextResponsePayload {
  org_id: string
  project_id: string
  project: ProjectInfoPayload
  projects: ProjectInfoPayload[]
}

export interface SwitchContextResponse {
  org_id: OrganizationId
  project_id: ProjectId
  project: ProjectInfo
  projects: ProjectInfo[]
}

export interface ProjectSummary {
  id: ProjectId
  org_id: OrganizationId
  name: string
  slug: string
  is_default: boolean
  archived_at?: string | null
  capability?: string
  triggers_paused?: boolean
}

export interface ProjectSummaryPage {
  data: ProjectSummary[]
  has_more: boolean
  first_id?: ProjectId
  last_id?: ProjectId
}

export interface OrganizationDetail {
  id: OrganizationId
  name: string
  slug: string
  logo?: string | null
  role: string
  owner_name?: string | null
  owner_email?: string | null
  project_creation_policy: 'admins_only' | 'all_members'
  created_at?: string | null
}

export interface OrganizationMemberRecord {
  id: OrganizationMemberId
  user_id: UserId
  organization_id: OrganizationId
  role: string
  user_name?: string | null
  user_email?: string | null
  joined_at?: string | null
}

export interface ProjectAccessRecord {
  id?: OrganizationMemberId
  user_id: UserId
  email: string
  display_name: string
  org_role: string
  access: string
  project_role?: string | null
  joined_at?: string | null
}

export interface MemberCandidate {
  id: UserId
  email: string
  name: string
  image?: string | null
  already_member: boolean
}

export interface OrganizationMemberPage {
  data: OrganizationMemberRecord[]
  has_more: boolean
  first_id?: OrganizationMemberId
  last_id?: OrganizationMemberId
}

export interface PlatformOrganization {
  id: OrganizationId
  name: string
  slug: string
  logo?: string | null
  member_count: number
  project_count: number
  member_emails: string[]
  created_at: string
}

export interface PlatformOrganizationPage {
  data: PlatformOrganization[]
}

export interface PlatformUser {
  id: UserId
  email: string
  name: string
  image?: string | null
  email_verified: boolean
  is_active: boolean
  is_super_user: boolean
  created_at: string
  updated_at: string
}

export function parseOrganizationInfo(raw: OrganizationInfoPayload): OrgInfo {
  return { ...raw, id: parseOrganizationId(raw.id) }
}

export function parseProjectInfo(raw: ProjectInfoPayload): ProjectInfo {
  return {
    ...raw,
    id: parseProjectId(raw.id),
    org_id: raw.org_id === undefined ? undefined : parseOrganizationId(raw.org_id),
  }
}

export function parseAuthContextResponse(raw: AuthContextResponsePayload): AuthContextResponse {
  return {
    ...raw,
    user: { ...raw.user, id: parseUserId(raw.user.id) },
    organization: parseOrganizationInfo(raw.organization),
    project: parseProjectInfo(raw.project),
    organizations: raw.organizations.map(parseOrganizationInfo),
    projects: raw.projects.map(parseProjectInfo),
  }
}

export function parseSwitchContextResponse(
  raw: SwitchContextResponsePayload,
): SwitchContextResponse {
  return {
    org_id: parseOrganizationId(raw.org_id),
    project_id: parseProjectId(raw.project_id),
    project: parseProjectInfo(raw.project),
    projects: raw.projects.map(parseProjectInfo),
  }
}

export function parseProjectSummaryResponse(response: unknown): ProjectSummary {
  const raw = responseRecord(response, 'project summary')
  const triggersPaused = raw.triggers_paused
  if (triggersPaused !== undefined && typeof triggersPaused !== 'boolean') {
    throw new TypeError('Expected project summary.triggers_paused to be a boolean')
  }
  return {
    id: parseProjectId(requiredString(raw, 'id', 'project summary')),
    org_id: parseOrganizationId(requiredString(raw, 'org_id', 'project summary')),
    name: requiredString(raw, 'name', 'project summary'),
    slug: requiredString(raw, 'slug', 'project summary'),
    is_default: requiredBoolean(raw, 'is_default', 'project summary'),
    archived_at: optionalNullableString(raw, 'archived_at', 'project summary'),
    capability: optionalNullableString(raw, 'capability', 'project summary') ?? undefined,
    triggers_paused: triggersPaused,
  }
}

export function parseProjectSummaryPageResponse(response: unknown): ProjectSummaryPage {
  const raw = responseRecord(response, 'project summary page')
  if (!Array.isArray(raw.data)) {
    throw new TypeError('Expected project summary page.data to be an array')
  }
  const firstId = optionalNullableString(raw, 'first_id', 'project summary page')
  const lastId = optionalNullableString(raw, 'last_id', 'project summary page')
  return {
    data: raw.data.map(parseProjectSummaryResponse),
    has_more: requiredBoolean(raw, 'has_more', 'project summary page'),
    first_id: parseOptionalId(firstId, parseProjectId) ?? undefined,
    last_id: parseOptionalId(lastId, parseProjectId) ?? undefined,
  }
}

export function parseOrganizationDetailResponse(response: unknown): OrganizationDetail {
  const raw = responseRecord(response, 'organization detail')
  const projectCreationPolicy = requiredString(
    raw,
    'project_creation_policy',
    'organization detail',
  )
  if (projectCreationPolicy !== 'admins_only' && projectCreationPolicy !== 'all_members') {
    throw new TypeError('Expected organization detail.project_creation_policy to be valid')
  }
  return {
    id: parseOrganizationId(requiredString(raw, 'id', 'organization detail')),
    name: requiredString(raw, 'name', 'organization detail'),
    slug: requiredString(raw, 'slug', 'organization detail'),
    logo: optionalNullableString(raw, 'logo', 'organization detail'),
    role: requiredString(raw, 'role', 'organization detail'),
    owner_name: optionalNullableString(raw, 'owner_name', 'organization detail'),
    owner_email: optionalNullableString(raw, 'owner_email', 'organization detail'),
    project_creation_policy: projectCreationPolicy,
    created_at: optionalNullableString(raw, 'created_at', 'organization detail'),
  }
}

export function parseOrganizationMemberResponse(response: unknown): OrganizationMemberRecord {
  const raw = responseRecord(response, 'organization member')
  return {
    id: parseOrganizationMemberId(requiredString(raw, 'id', 'organization member')),
    user_id: parseUserId(requiredString(raw, 'user_id', 'organization member')),
    organization_id: parseOrganizationId(
      requiredString(raw, 'organization_id', 'organization member'),
    ),
    role: requiredString(raw, 'role', 'organization member'),
    user_name: optionalNullableString(raw, 'user_name', 'organization member'),
    user_email: optionalNullableString(raw, 'user_email', 'organization member'),
    joined_at: optionalNullableString(raw, 'joined_at', 'organization member'),
  }
}

export function parseProjectAccessRecordResponse(response: unknown): ProjectAccessRecord {
  const raw = responseRecord(response, 'project access record')
  const rawId = optionalNullableString(raw, 'id', 'project access record')
  return {
    id: parseOptionalId(rawId, parseOrganizationMemberId) ?? undefined,
    user_id: parseUserId(requiredString(raw, 'user_id', 'project access record')),
    email: requiredString(raw, 'email', 'project access record'),
    display_name: requiredString(raw, 'display_name', 'project access record'),
    org_role: requiredString(raw, 'org_role', 'project access record'),
    access: requiredString(raw, 'access', 'project access record'),
    project_role: optionalNullableString(raw, 'project_role', 'project access record'),
    joined_at: optionalNullableString(raw, 'joined_at', 'project access record'),
  }
}

export function parseMemberCandidateResponse(response: unknown): MemberCandidate {
  const raw = responseRecord(response, 'member candidate')
  return {
    id: parseUserId(requiredString(raw, 'id', 'member candidate')),
    email: requiredString(raw, 'email', 'member candidate'),
    name: requiredString(raw, 'name', 'member candidate'),
    image: optionalNullableString(raw, 'image', 'member candidate'),
    already_member: requiredBoolean(raw, 'already_member', 'member candidate'),
  }
}

export function parseOrganizationMemberPageResponse(response: unknown): OrganizationMemberPage {
  const raw = responseRecord(response, 'organization member page')
  if (!Array.isArray(raw.data)) {
    throw new TypeError('Expected organization member page.data to be an array')
  }
  const firstId = optionalNullableString(raw, 'first_id', 'organization member page')
  const lastId = optionalNullableString(raw, 'last_id', 'organization member page')
  return {
    data: raw.data.map(parseOrganizationMemberResponse),
    has_more: requiredBoolean(raw, 'has_more', 'organization member page'),
    first_id: parseOptionalId(firstId, parseOrganizationMemberId) ?? undefined,
    last_id: parseOptionalId(lastId, parseOrganizationMemberId) ?? undefined,
  }
}

export function parseMemberCandidateListResponse(response: unknown): MemberCandidate[] {
  if (!Array.isArray(response)) {
    throw new TypeError('Expected member candidates to be an array')
  }
  return response.map(parseMemberCandidateResponse)
}

export function parsePlatformOrganizationResponse(response: unknown): PlatformOrganization {
  const raw = responseRecord(response, 'platform organization')
  return {
    id: parseOrganizationId(requiredString(raw, 'id', 'platform organization')),
    name: requiredString(raw, 'name', 'platform organization'),
    slug: requiredString(raw, 'slug', 'platform organization'),
    logo: optionalNullableString(raw, 'logo', 'platform organization'),
    member_count: requiredNumber(raw, 'member_count', 'platform organization'),
    project_count: requiredNumber(raw, 'project_count', 'platform organization'),
    member_emails: requiredStringList(raw, 'member_emails', 'platform organization'),
    created_at: requiredString(raw, 'created_at', 'platform organization'),
  }
}

export function parsePlatformUserResponse(response: unknown): PlatformUser {
  const raw = responseRecord(response, 'platform user')
  return {
    id: parseUserId(requiredString(raw, 'id', 'platform user')),
    email: requiredString(raw, 'email', 'platform user'),
    name: requiredString(raw, 'name', 'platform user'),
    image: optionalNullableString(raw, 'image', 'platform user'),
    email_verified: requiredBoolean(raw, 'email_verified', 'platform user'),
    is_active: requiredBoolean(raw, 'is_active', 'platform user'),
    is_super_user: requiredBoolean(raw, 'is_super_user', 'platform user'),
    created_at: requiredString(raw, 'created_at', 'platform user'),
    updated_at: requiredString(raw, 'updated_at', 'platform user'),
  }
}

export function parsePlatformOrganizationPageResponse(response: unknown): PlatformOrganizationPage {
  const raw = responseRecord(response, 'platform organization page')
  if (!Array.isArray(raw.data)) {
    throw new TypeError('Expected platform organization page.data to be an array')
  }
  return { data: raw.data.map(parsePlatformOrganizationResponse) }
}
