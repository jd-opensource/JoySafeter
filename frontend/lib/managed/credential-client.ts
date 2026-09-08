import { managedDelete, managedGet, managedPatch, managedPost } from '@/lib/api-client'
import { apiCollectionPath, apiResourcePath } from '@/lib/managed/api-paths'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import { type CredentialGroupId, parseCredentialId, type CredentialId } from '@/types/entity-id'
import type { Credential, CredentialDetail } from '@/types/managed'

import {
  filterSelectableCredentials,
  parseCredentialDetailResponse,
  parseCredentialResponse,
} from './credential-response-parsers'
import {
  collectManagedCursorPages,
  parseManagedCursorPage,
  type ManagedCursorPage,
} from './cursor-page'

const CREDENTIAL_OPTION_PAGE_SIZE = 100

export interface ManagedCredentialPageRequest {
  limit?: number
  afterId?: CredentialId
  includeArchived?: boolean
  kind?: Credential['kind']
  name?: string
  provider?: string
  protocol?: string
  compatibleEngine?: string
  compatibleConsumer?: string
}

export interface ManagedCredentialCreateInput {
  kind: Credential['kind']
  name: string
  data: Record<string, string>
  authScheme?: string
  provider?: string
  protocol?: string
  isDefault?: boolean
  mcpServerUrl?: string
  groupId?: CredentialGroupId
}

export interface ManagedCredentialUpdateInput {
  name?: string
  data?: Record<string, string>
  authScheme?: string
  isDefault?: boolean
}

export interface ManagedCredentialTestInput {
  provider: string
  protocol: string
  data: Record<string, string>
  authScheme?: string
}

export interface ManagedCredentialTestResult {
  ok: boolean
  message: string
}

export type ManagedCredentialLifecycleAction = 'archive' | 'restore'

export const MANAGED_CREDENTIALS_QUERY_ROOT = 'credentials'

export function managedCredentialListSourceKey(kind: Credential['kind']) {
  return `managed-${kind}-credential-list`
}

export function managedCredentialQueryKey(scopeKey: string, credentialId: CredentialId | null) {
  return ['credential-detail', scopeKey, credentialId] as const
}

export function managedCredentialsQueryPrefix(scopeKey: string) {
  return [MANAGED_CREDENTIALS_QUERY_ROOT, scopeKey] as const
}

export function serviceCredentialsQueryKey(scopeKey: string) {
  return [MANAGED_CREDENTIALS_QUERY_ROOT, scopeKey, 'options', 'service', false] as const
}

export function compatibleCredentialsScopePrefix(scopeKey: string) {
  return ['compatible-credentials', scopeKey] as const
}

export function compatibleCredentialsQueryPrefix(scopeKey: string, engineId: string) {
  return [...compatibleCredentialsScopePrefix(scopeKey), engineId] as const
}

export function consumerCredentialsQueryPrefix(scopeKey: string, modelConsumerId: string) {
  return ['consumer-credentials', scopeKey, modelConsumerId] as const
}

export function activeModelConnectionsQueryPrefix(scopeKey: string) {
  return ['active-model-connections', scopeKey] as const
}

export function activeModelConnectionsQueryKey(scopeKey: string, catalogVersion = '') {
  return [...activeModelConnectionsQueryPrefix(scopeKey), catalogVersion] as const
}

export function compatibleCredentialsQueryKey(
  scopeKey: string,
  engineId: string,
  catalogVersion = '',
) {
  return [...compatibleCredentialsQueryPrefix(scopeKey, engineId), catalogVersion] as const
}

export function consumerCredentialsQueryKey(
  scopeKey: string,
  modelConsumerId: string,
  catalogVersion = '',
) {
  return [...consumerCredentialsQueryPrefix(scopeKey, modelConsumerId), catalogVersion] as const
}

export function modelConnectionByNameQueryKey(scopeKey: string, name: string, catalogVersion = '') {
  return ['model-connection-by-name', scopeKey, name, catalogVersion] as const
}

export function protocolCredentialsQueryKey(
  scopeKey: string,
  protocolId: string,
  catalogVersion = '',
) {
  return ['protocol-credentials', scopeKey, protocolId, catalogVersion] as const
}

export function protocolCredentialsQueryPrefix(scopeKey: string, protocolId: string) {
  return ['protocol-credentials', scopeKey, protocolId] as const
}

export async function fetchManagedCredentials(
  request: ManagedCredentialPageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedCursorPage<Credential, CredentialId>> {
  const response = await managedGet<unknown>(
    apiCollectionPath('credentials', {
      limit: request.limit,
      after_id: request.afterId,
      kind: request.kind,
      include_archived: request.includeArchived,
      name: request.name,
      provider: request.provider,
      protocol: request.protocol,
      compatible_engine: request.compatibleEngine,
      compatible_consumer: request.compatibleConsumer,
    }),
    managedRequestOptions(requestScope),
  )
  return parseManagedCursorPage(response, {
    parseItem: parseCredentialResponse,
    parseCursor: parseCredentialId,
    responseName: 'Credential list response',
  })
}

export async function fetchManagedCredential(
  credentialId: CredentialId,
  requestScope: ManagedRequestScope,
): Promise<CredentialDetail> {
  const response = await managedGet<unknown>(
    apiResourcePath('credentials', credentialId),
    managedRequestOptions(requestScope),
  )
  return parseCredentialDetailResponse(response)
}

export async function createManagedCredential(
  input: ManagedCredentialCreateInput,
  requestScope: ManagedRequestScope,
): Promise<CredentialDetail> {
  const response = await managedPost<unknown>(
    apiCollectionPath('credentials'),
    {
      kind: input.kind,
      name: input.name,
      data: input.data,
      ...(input.authScheme !== undefined ? { auth_scheme: input.authScheme } : {}),
      ...(input.provider !== undefined ? { provider: input.provider } : {}),
      ...(input.protocol !== undefined ? { protocol: input.protocol } : {}),
      ...(input.isDefault !== undefined ? { is_default: input.isDefault } : {}),
      ...(input.mcpServerUrl !== undefined ? { mcp_server_url: input.mcpServerUrl } : {}),
      ...(input.groupId !== undefined ? { group_id: input.groupId } : {}),
    },
    managedRequestOptions(requestScope),
  )
  return parseCredentialDetailResponse(response)
}

export async function updateManagedCredential(
  credentialId: CredentialId,
  input: ManagedCredentialUpdateInput,
  requestScope: ManagedRequestScope,
): Promise<CredentialDetail> {
  const response = await managedPatch<unknown>(
    apiResourcePath('credentials', credentialId),
    {
      ...(input.name !== undefined ? { name: input.name } : {}),
      ...(input.data !== undefined ? { data: input.data } : {}),
      ...(input.authScheme !== undefined ? { auth_scheme: input.authScheme } : {}),
      ...(input.isDefault !== undefined ? { is_default: input.isDefault } : {}),
    },
    managedRequestOptions(requestScope),
  )
  return parseCredentialDetailResponse(response)
}

export async function deleteManagedCredential(
  credentialId: CredentialId,
  requestScope: ManagedRequestScope,
): Promise<void> {
  await managedDelete<void>(
    apiResourcePath('credentials', credentialId),
    managedRequestOptions(requestScope),
  )
}

export async function setManagedCredentialDefault(
  credentialId: CredentialId,
  requestScope: ManagedRequestScope,
): Promise<CredentialDetail> {
  const response = await managedPost<unknown>(
    apiResourcePath('credentials', credentialId, 'default'),
    {},
    managedRequestOptions(requestScope),
  )
  return parseCredentialDetailResponse(response)
}

export async function changeManagedCredentialLifecycle(
  credentialId: CredentialId,
  action: ManagedCredentialLifecycleAction,
  requestScope: ManagedRequestScope,
): Promise<CredentialDetail> {
  const response = await managedPost<unknown>(
    apiResourcePath('credentials', credentialId, action),
    {},
    managedRequestOptions(requestScope),
  )
  return parseCredentialDetailResponse(response)
}

export async function testManagedCredential(
  input: ManagedCredentialTestInput,
  requestScope: ManagedRequestScope,
): Promise<ManagedCredentialTestResult> {
  const response = await managedPost<unknown>(
    apiCollectionPath('credentials/test'),
    {
      provider: input.provider,
      protocol: input.protocol,
      data: input.data,
      ...(input.authScheme !== undefined ? { auth_scheme: input.authScheme } : {}),
    },
    managedRequestOptions(requestScope),
  )
  if (!response || typeof response !== 'object' || Array.isArray(response)) {
    throw new TypeError('Expected Credential test response to be an object')
  }
  const { ok, message } = response as { ok?: unknown; message?: unknown }
  if (typeof ok !== 'boolean' || typeof message !== 'string') {
    throw new TypeError('Expected Credential test response fields to be valid')
  }
  return { ok, message }
}

export async function fetchManagedCredentialOptions(
  request: Omit<ManagedCredentialPageRequest, 'limit' | 'afterId'>,
  requestScope: ManagedRequestScope,
  responseName: string,
): Promise<Credential[]> {
  return collectManagedCursorPages<Credential, CredentialId>({
    responseName,
    fetchPage: (afterId) =>
      fetchManagedCredentials(
        { ...request, limit: CREDENTIAL_OPTION_PAGE_SIZE, afterId },
        requestScope,
      ),
  })
}

export async function fetchManagedServiceCredentialOptions(
  requestScope: ManagedRequestScope,
): Promise<Credential[]> {
  const credentials = await fetchManagedCredentialOptions(
    { kind: 'service', includeArchived: false },
    requestScope,
    'Service Credential pagination',
  )
  return filterSelectableCredentials(credentials)
}

export function fetchManagedModelCredentialOptions(
  request: Pick<
    ManagedCredentialPageRequest,
    'name' | 'provider' | 'protocol' | 'compatibleEngine' | 'compatibleConsumer'
  >,
  requestScope: ManagedRequestScope,
  responseName: string,
): Promise<Credential[]> {
  return fetchManagedCredentialOptions(
    { ...request, kind: 'model', includeArchived: false },
    requestScope,
    responseName,
  )
}

export async function fetchManagedModelConnectionByName(
  name: string,
  requestScope: ManagedRequestScope,
): Promise<Credential | null> {
  const page = await fetchManagedCredentials({ limit: 1, kind: 'model', name }, requestScope)
  return page.items.find((credential) => credential.name === name) ?? null
}
