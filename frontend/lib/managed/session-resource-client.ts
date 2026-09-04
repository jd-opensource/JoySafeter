import { managedDelete, managedGet, managedPatch, managedPost } from '@/lib/api-client'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import {
  parseFileId,
  parseSessionResourceId,
  type FileId,
  type SessionId,
  type SessionResourceId,
} from '@/types/entity-id'
import type { SessionFileResource, SessionRepoResource, SessionResource } from '@/types/managed'

import {
  parseSessionFileResourceResponse,
  parseSessionRepoResourceResponse,
  parseSessionResourceListResponse,
} from './file-response-parsers'

export interface ManagedSessionFileResourceInput {
  fileId: FileId
  mountPath?: string
}

export interface ManagedSessionFileResourceBody {
  type: 'file'
  file_id: FileId
  mount_path?: string
}

export interface ManagedSessionRepositoryResourceInput {
  url: string
  branch?: string
  mountPath?: string
  mountName?: string
  authorizationToken?: string
  tokenExpiresAt?: string
}

export interface ManagedSessionRepositoryResourceBody {
  type: 'github_repository'
  url: string
  branch?: string
  mount_path?: string
  mount_name?: string
  authorization_token?: string
  token_expires_at?: string
}

export interface ManagedSessionRepositoryTokenInput {
  authorizationToken: string
  tokenExpiresAt?: string
}

export function managedSessionResourcesQueryKey(scopeKey: string, sessionId: SessionId) {
  return ['session-resources', scopeKey, sessionId] as const
}

export function buildManagedSessionFileResourceBody(
  input: ManagedSessionFileResourceInput,
): ManagedSessionFileResourceBody {
  return {
    type: 'file',
    file_id: parseFileId(input.fileId),
    ...(input.mountPath ? { mount_path: input.mountPath } : {}),
  }
}

export function buildManagedSessionRepositoryResourceBody(
  input: ManagedSessionRepositoryResourceInput,
): ManagedSessionRepositoryResourceBody {
  return {
    type: 'github_repository',
    url: input.url,
    ...(input.branch ? { branch: input.branch } : {}),
    ...(input.mountPath ? { mount_path: input.mountPath } : {}),
    ...(input.mountName ? { mount_name: input.mountName } : {}),
    ...(input.authorizationToken ? { authorization_token: input.authorizationToken } : {}),
    ...(input.tokenExpiresAt ? { token_expires_at: input.tokenExpiresAt } : {}),
  }
}

export async function fetchManagedSessionResources(
  sessionId: SessionId,
  requestScope: ManagedRequestScope,
): Promise<SessionResource[]> {
  const response = await managedGet<{ data: unknown[] }>(
    apiResourcePath('sessions', sessionId, 'resources'),
    managedRequestOptions(requestScope),
  )
  return parseSessionResourceListResponse(response.data)
}

export async function addManagedSessionFileResource(
  sessionId: SessionId,
  input: ManagedSessionFileResourceInput,
  requestScope: ManagedRequestScope,
): Promise<SessionFileResource> {
  const response = await managedPost<unknown>(
    apiResourcePath('sessions', sessionId, 'resources'),
    buildManagedSessionFileResourceBody(input),
    managedRequestOptions(requestScope),
  )
  return parseSessionFileResourceResponse(response)
}

export async function addManagedSessionRepositoryResource(
  sessionId: SessionId,
  input: ManagedSessionRepositoryResourceInput,
  requestScope: ManagedRequestScope,
): Promise<SessionRepoResource> {
  const response = await managedPost<unknown>(
    apiResourcePath('sessions', sessionId, 'resources'),
    buildManagedSessionRepositoryResourceBody(input),
    managedRequestOptions(requestScope),
  )
  return parseSessionRepoResourceResponse(response)
}

export async function removeManagedSessionResource(
  sessionId: SessionId,
  resourceId: SessionResourceId,
  requestScope: ManagedRequestScope,
): Promise<SessionResourceId> {
  const response = await managedDelete<unknown>(
    apiResourcePath('sessions', sessionId, 'resources', resourceId),
    managedRequestOptions(requestScope),
  )
  const raw = response as { id?: unknown }
  if (typeof raw?.id !== 'string') throw new Error('Invalid deleted session resource id')
  const deletedResourceId = parseSessionResourceId(raw.id)
  if (deletedResourceId !== resourceId) {
    throw new Error('Mismatched deleted session resource id')
  }
  return deletedResourceId
}

export async function rotateManagedSessionRepositoryToken(
  sessionId: SessionId,
  resourceId: SessionResourceId,
  input: ManagedSessionRepositoryTokenInput,
  requestScope: ManagedRequestScope,
): Promise<SessionRepoResource> {
  const response = await managedPatch<unknown>(
    apiResourcePath('sessions', sessionId, 'resources', resourceId),
    {
      authorization_token: input.authorizationToken,
      ...(input.tokenExpiresAt ? { token_expires_at: input.tokenExpiresAt } : {}),
    },
    managedRequestOptions(requestScope),
  )
  return parseSessionRepoResourceResponse(response)
}
