import { managedDelete, managedGet, managedPost, managedPut, managedUpload } from '@/lib/api-client'
import { apiCollectionPath, apiResourcePath, apiResourceSubpath } from '@/lib/managed/api-paths'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import {
  parseSkillId,
  parseSkillSecurityScanId,
  parseSkillUsageId,
  parseSkillVersionId,
  type SkillFileId,
  type SkillId,
  type SkillSecurityScanId,
  type SkillUsageId,
  type SkillVersionId,
} from '@/types/entity-id'
import type {
  PromotableTier,
  SessionSkillUsage,
  SkillFileRecord,
  SkillRecord,
  SkillSecurityScanRecord,
  SkillVersionFileRecord,
  SkillVersionRecord,
} from '@/types/managed'

import {
  collectManagedCursorPages,
  parseManagedCursorPage,
  type ManagedCursorPage,
} from './cursor-page'
import {
  parseSkillAuthoringSaveResponse,
  parseSkillDeleteResponse,
  parseSkillFileDeleteResponse,
  parseSkillFileResponse,
  parseSkillLifecycleTransitionResponse,
  parseSkillResponse,
  parseSkillSecurityScanResponse,
  parseSkillUsageResponse,
  parseSkillVersionDeleteResponse,
  parseSkillVersionFileResponse,
  parseSkillVersionResponse,
  type SkillAuthoringSaveResponse,
  type SkillDeleteResponse,
  type SkillFileDeleteResponse,
  type SkillLifecycleTransitionResponse,
  type SkillVersionDeleteResponse,
} from './skill-response-parsers'

const SKILL_OPTION_PAGE_SIZE = 100
const SKILL_VERSION_OPTION_PAGE_SIZE = 100
const SKILL_SECURITY_HISTORY_PAGE_SIZE = 100
const SKILL_MUTATION_TIMEOUT_MS = 200_000

export interface ManagedSkillCreateInput {
  name: string
  description?: string
  content?: string
  tags?: string[]
  license?: string
  source_type?: string
  source_url?: string
  files?: Array<Pick<SkillFileRecord, 'path' | 'file_name' | 'file_type' | 'content' | 'size'>>
}

export interface ManagedSkillUpdateInput {
  name?: string
  description?: string
  content?: string
  license?: string
  tags?: string[]
  source_type?: string
  source_url?: string
}

export interface ManagedSkillFileCreateInput {
  path: string
  file_name: string
  file_type?: string
  content?: string
}

export interface ManagedSkillFileUpdateInput {
  path?: string
  file_name?: string
  content?: string
}

export interface ManagedSkillVersionPublishInput {
  version?: string
  release_notes?: string
}

export interface ManagedSkillAuthoringSaveInput {
  draft_skill_id: SkillId | null
  name: string
  description: string
  content: string
  tags: string[]
  files: Array<{ path: string; content: string }>
}

export type ManagedSkillLifecycleTransition =
  | 'submit-review'
  | 'approve'
  | 'reject'
  | 'reopen'
  | 'archive'
  | 'unarchive'

export interface ManagedSkillPageRequest {
  limit?: number
  afterId?: SkillId
}

export interface ManagedSkillVersionPageRequest {
  limit?: number
  afterId?: SkillVersionId
}

export interface ManagedSkillSecurityScanPageRequest {
  limit?: number
  afterId?: SkillSecurityScanId
}

export interface ManagedSkillUsageRequest {
  limit: number
  artifactHash?: string | null
  targetHash?: string | null
  securityScanId?: SkillSecurityScanId | null
}

export const MANAGED_SKILLS_QUERY_ROOT = 'skills'
export const MANAGED_SKILLS_SOURCE_KEY = 'managed-skill-list'

export function managedSkillScopeQueryPrefix(scopeKey: string) {
  return [MANAGED_SKILLS_QUERY_ROOT, scopeKey] as const
}

export function managedSkillListQueryPrefix(scopeKey: string) {
  return [...managedSkillScopeQueryPrefix(scopeKey), MANAGED_SKILLS_SOURCE_KEY] as const
}

export function managedSkillOptionsQueryKey(scopeKey: string) {
  return [MANAGED_SKILLS_QUERY_ROOT, scopeKey, 'options'] as const
}

export function managedSkillQueryKey(scopeKey: string, skillId: SkillId | null) {
  return [MANAGED_SKILLS_QUERY_ROOT, scopeKey, skillId, 'detail'] as const
}

export function managedSkillFilesQueryKey(scopeKey: string, skillId: SkillId | null) {
  return [MANAGED_SKILLS_QUERY_ROOT, scopeKey, skillId, 'files'] as const
}

export function managedSkillVersionsQueryKey(scopeKey: string, skillId: SkillId | null) {
  return [MANAGED_SKILLS_QUERY_ROOT, scopeKey, skillId, 'versions'] as const
}

export function managedSkillVersionFilesQueryKey(
  scopeKey: string,
  skillId: SkillId,
  version: string | null,
) {
  return [MANAGED_SKILLS_QUERY_ROOT, scopeKey, skillId, 'versions', version, 'files'] as const
}

export function managedSkillSecurityHistoryQueryKey(scopeKey: string, skillId: SkillId | null) {
  return [MANAGED_SKILLS_QUERY_ROOT, scopeKey, skillId, 'security-scans'] as const
}

export function managedSkillRecentUsageQueryKey(scopeKey: string, skillId: SkillId | null) {
  return [MANAGED_SKILLS_QUERY_ROOT, scopeKey, skillId, 'usage', 'recent'] as const
}

export function managedSkillTargetUsageQueryKey(scopeKey: string, targetHash: string | null) {
  return [MANAGED_SKILLS_QUERY_ROOT, scopeKey, 'usage', 'target-hash', targetHash] as const
}

function parseManagedDataCollection<Item>(
  response: unknown,
  parseItem: (item: unknown) => Item,
  responseName: string,
): Item[] {
  if (!response || typeof response !== 'object' || Array.isArray(response)) {
    throw new Error(`Invalid ${responseName}`)
  }
  const data = (response as { data?: unknown }).data
  if (!Array.isArray(data)) throw new Error(`Invalid ${responseName}`)
  return data.map(parseItem)
}

export async function fetchManagedSkill(
  skillId: SkillId,
  requestScope: ManagedRequestScope,
): Promise<SkillRecord> {
  const response = await managedGet<unknown>(
    apiResourcePath('skills', skillId),
    managedRequestOptions(requestScope),
  )
  return parseSkillResponse(response)
}

export function createManagedSkill(
  input: ManagedSkillCreateInput,
  requestScope: ManagedRequestScope,
): Promise<SkillRecord> {
  return managedPost<unknown>('/skills', input, {
    ...managedRequestOptions(requestScope),
    timeout: SKILL_MUTATION_TIMEOUT_MS,
  }).then(parseSkillResponse)
}

export function importManagedSkillZip(
  file: File,
  requestScope: ManagedRequestScope,
): Promise<SkillRecord> {
  const formData = new FormData()
  formData.append('file', file)
  return managedUpload<unknown>(
    '/skills/import-zip',
    formData,
    managedRequestOptions(requestScope),
  ).then(parseSkillResponse)
}

export function updateManagedSkill(
  skillId: SkillId,
  input: ManagedSkillUpdateInput,
  requestScope: ManagedRequestScope,
): Promise<SkillRecord> {
  return managedPut<unknown>(apiResourcePath('skills', skillId), input, {
    ...managedRequestOptions(requestScope),
    timeout: SKILL_MUTATION_TIMEOUT_MS,
  }).then(parseSkillResponse)
}

export function deleteManagedSkill(
  skillId: SkillId,
  requestScope: ManagedRequestScope,
): Promise<SkillDeleteResponse> {
  return managedDelete<unknown>(
    apiResourcePath('skills', skillId),
    managedRequestOptions(requestScope),
  ).then(parseSkillDeleteResponse)
}

export async function fetchManagedSkillFiles(
  skillId: SkillId,
  requestScope: ManagedRequestScope,
): Promise<SkillFileRecord[]> {
  const response = await managedGet<unknown>(
    apiResourcePath('skills', skillId, 'files'),
    managedRequestOptions(requestScope),
  )
  return parseManagedDataCollection(response, parseSkillFileResponse, 'Skill file list response')
}

export function createManagedSkillFile(
  skillId: SkillId,
  input: ManagedSkillFileCreateInput,
  requestScope: ManagedRequestScope,
): Promise<SkillFileRecord> {
  return managedPost<unknown>(apiResourcePath('skills', skillId, 'files'), input, {
    ...managedRequestOptions(requestScope),
    timeout: SKILL_MUTATION_TIMEOUT_MS,
  }).then(parseSkillFileResponse)
}

export function updateManagedSkillFile(
  skillId: SkillId,
  fileId: SkillFileId,
  input: ManagedSkillFileUpdateInput,
  requestScope: ManagedRequestScope,
): Promise<SkillFileRecord> {
  return managedPut<unknown>(apiResourcePath('skills', skillId, 'files', fileId), input, {
    ...managedRequestOptions(requestScope),
    timeout: SKILL_MUTATION_TIMEOUT_MS,
  }).then(parseSkillFileResponse)
}

export function deleteManagedSkillFile(
  skillId: SkillId,
  fileId: SkillFileId,
  requestScope: ManagedRequestScope,
): Promise<SkillFileDeleteResponse> {
  return managedDelete<unknown>(
    apiResourcePath('skills', skillId, 'files', fileId),
    managedRequestOptions(requestScope),
  ).then(parseSkillFileDeleteResponse)
}

export async function fetchManagedSkillVersionFiles(
  skillId: SkillId,
  version: string,
  requestScope: ManagedRequestScope,
): Promise<SkillVersionFileRecord[]> {
  const response = await managedGet<unknown>(
    apiResourcePath('skills', skillId, 'versions', version, 'files'),
    managedRequestOptions(requestScope),
  )
  return parseManagedDataCollection(
    response,
    parseSkillVersionFileResponse,
    'Skill version file list response',
  )
}

export async function fetchManagedSkills(
  request: ManagedSkillPageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedCursorPage<SkillRecord, SkillId>> {
  const response = await managedGet<unknown>(
    apiCollectionPath('skills', {
      limit: request.limit,
      after_id: request.afterId,
    }),
    managedRequestOptions(requestScope),
  )
  return parseManagedCursorPage(response, {
    parseItem: parseSkillResponse,
    parseCursor: parseSkillId,
    responseName: 'Skill list response',
  })
}

export function fetchManagedSkillOptions(
  requestScope: ManagedRequestScope,
): Promise<SkillRecord[]> {
  return collectManagedCursorPages<SkillRecord, SkillId>({
    responseName: 'Skill options pagination',
    fetchPage: (afterId) =>
      fetchManagedSkills({ limit: SKILL_OPTION_PAGE_SIZE, afterId }, requestScope),
  })
}

export async function fetchManagedSkillVersions(
  skillId: SkillId,
  request: ManagedSkillVersionPageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedCursorPage<SkillVersionRecord, SkillVersionId>> {
  const response = await managedGet<unknown>(
    apiResourceSubpath('skills', skillId, ['versions'], {
      limit: request.limit,
      after_id: request.afterId,
    }),
    managedRequestOptions(requestScope),
  )
  return parseManagedCursorPage(response, {
    parseItem: parseSkillVersionResponse,
    parseCursor: parseSkillVersionId,
    responseName: 'Skill version list response',
  })
}

export function fetchManagedSkillVersionOptions(
  skillId: SkillId,
  requestScope: ManagedRequestScope,
): Promise<SkillVersionRecord[]> {
  return collectManagedCursorPages<SkillVersionRecord, SkillVersionId>({
    responseName: 'Skill version options pagination',
    fetchPage: (afterId) =>
      fetchManagedSkillVersions(
        skillId,
        { limit: SKILL_VERSION_OPTION_PAGE_SIZE, afterId },
        requestScope,
      ),
  })
}

export function publishManagedSkillVersion(
  skillId: SkillId,
  input: ManagedSkillVersionPublishInput,
  requestScope: ManagedRequestScope,
): Promise<SkillVersionRecord> {
  return managedPost<unknown>(
    apiResourcePath('skills', skillId, 'versions'),
    { ...input, release_notes: input.release_notes ?? '' },
    managedRequestOptions(requestScope),
  ).then(parseSkillVersionResponse)
}

export function deleteManagedSkillVersion(
  skillId: SkillId,
  version: string,
  force: boolean,
  requestScope: ManagedRequestScope,
): Promise<SkillVersionDeleteResponse> {
  return managedDelete<unknown>(
    apiResourceSubpath('skills', skillId, ['versions', version], {
      force: force || undefined,
    }),
    managedRequestOptions(requestScope),
  ).then(parseSkillVersionDeleteResponse)
}

export function restoreManagedSkillVersion(
  skillId: SkillId,
  version: string,
  requestScope: ManagedRequestScope,
): Promise<SkillRecord> {
  return managedPost<unknown>(
    apiResourcePath('skills', skillId, 'versions', 'restore', version),
    {},
    managedRequestOptions(requestScope),
  ).then(parseSkillResponse)
}

export function submitManagedSkillPromotion(
  skillId: SkillId,
  version: string,
  targetTier: PromotableTier,
  requestScope: ManagedRequestScope,
): Promise<SkillVersionRecord> {
  return managedPost<unknown>(
    apiResourcePath('skills', skillId, 'versions', version, 'submit-promotion'),
    { target_tier: targetTier },
    managedRequestOptions(requestScope),
  ).then(parseSkillVersionResponse)
}

export function approveManagedSkillPromotion(
  skillId: SkillId,
  version: string,
  requestScope: ManagedRequestScope,
): Promise<SkillVersionRecord> {
  return managedPost<unknown>(
    apiResourcePath('skills', skillId, 'versions', version, 'approve-promotion'),
    {},
    managedRequestOptions(requestScope),
  ).then(parseSkillVersionResponse)
}

export function rejectManagedSkillPromotion(
  skillId: SkillId,
  version: string,
  reason: string,
  requestScope: ManagedRequestScope,
): Promise<SkillVersionRecord> {
  return managedPost<unknown>(
    apiResourcePath('skills', skillId, 'versions', version, 'reject-promotion'),
    { reason: reason || null },
    managedRequestOptions(requestScope),
  ).then(parseSkillVersionResponse)
}

export function takedownManagedSkill(
  skillId: SkillId,
  tier: PromotableTier,
  requestScope: ManagedRequestScope,
): Promise<SkillRecord> {
  return managedPost<unknown>(
    apiResourcePath('skills', skillId, 'takedown'),
    { tier },
    managedRequestOptions(requestScope),
  ).then(parseSkillResponse)
}

export function transitionManagedSkillLifecycle(
  skillId: SkillId,
  transition: ManagedSkillLifecycleTransition,
  requestScope: ManagedRequestScope,
): Promise<SkillLifecycleTransitionResponse> {
  return managedPost<unknown>(
    apiResourcePath('skills', skillId, transition),
    {},
    managedRequestOptions(requestScope),
  ).then(parseSkillLifecycleTransitionResponse)
}

export async function fetchManagedSkillSecurityScans(
  skillId: SkillId,
  request: ManagedSkillSecurityScanPageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedCursorPage<SkillSecurityScanRecord, SkillSecurityScanId>> {
  const response = await managedGet<unknown>(
    apiResourceSubpath('skills', skillId, ['security-scans'], {
      limit: request.limit,
      after_id: request.afterId,
    }),
    managedRequestOptions(requestScope),
  )
  return parseManagedCursorPage(response, {
    parseItem: parseSkillSecurityScanResponse,
    parseCursor: parseSkillSecurityScanId,
    responseName: 'Skill security scan list response',
  })
}

export function fetchManagedSkillSecurityHistory(
  skillId: SkillId,
  requestScope: ManagedRequestScope,
): Promise<SkillSecurityScanRecord[]> {
  return collectManagedCursorPages<SkillSecurityScanRecord, SkillSecurityScanId>({
    responseName: 'Skill security history pagination',
    fetchPage: (afterId) =>
      fetchManagedSkillSecurityScans(
        skillId,
        { limit: SKILL_SECURITY_HISTORY_PAGE_SIZE, afterId },
        requestScope,
      ),
  })
}

export function fetchManagedLatestSkillSecurityScan(
  skillId: SkillId,
  requestScope: ManagedRequestScope,
): Promise<SkillSecurityScanRecord> {
  return managedGet<unknown>(
    apiResourcePath('skills', skillId, 'security-scans', 'latest'),
    managedRequestOptions(requestScope),
  ).then(parseSkillSecurityScanResponse)
}

async function fetchManagedSkillUsagePage(
  path: string,
  request: ManagedSkillUsageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedCursorPage<SessionSkillUsage, SkillUsageId>> {
  const response = await managedGet<unknown>(
    apiCollectionPath(path, {
      limit: request.limit,
      artifact_hash: request.artifactHash,
      target_hash: request.targetHash,
      security_scan_id: request.securityScanId,
    }),
    managedRequestOptions(requestScope),
  )
  return parseManagedCursorPage(response, {
    parseItem: parseSkillUsageResponse,
    parseCursor: parseSkillUsageId,
    responseName: 'Skill usage list response',
  })
}

export async function fetchManagedSkillRecentUsage(
  skillId: SkillId,
  requestScope: ManagedRequestScope,
): Promise<SessionSkillUsage[]> {
  const page = await fetchManagedSkillUsagePage(
    `skills/${skillId}/usage`,
    { limit: 5 },
    requestScope,
  )
  return page.items
}

export async function fetchManagedSkillTargetUsage(
  targetHash: string,
  requestScope: ManagedRequestScope,
): Promise<SessionSkillUsage[]> {
  const page = await fetchManagedSkillUsagePage(
    'skills/usage/search',
    { limit: 5, targetHash },
    requestScope,
  )
  return page.items
}

export function rescanManagedSkillSecurity(
  skillId: SkillId,
  requestScope: ManagedRequestScope,
): Promise<SkillSecurityScanRecord> {
  return managedPost<unknown>(
    apiResourcePath('skills', skillId, 'security-scans', 'rescan'),
    {},
    managedRequestOptions(requestScope),
  ).then(parseSkillSecurityScanResponse)
}

export function saveManagedSkillAuthoringDraft(
  input: ManagedSkillAuthoringSaveInput,
  requestScope: ManagedRequestScope,
): Promise<SkillAuthoringSaveResponse> {
  return managedPost<unknown>(
    'skills/ai-authoring/save-draft',
    input,
    managedRequestOptions(requestScope),
  ).then(parseSkillAuthoringSaveResponse)
}
