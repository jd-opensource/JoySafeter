import { managedGet, managedPost } from '@/lib/api-client'
import {
  apiCollectionPath,
  apiResourceId,
  apiResourcePath,
  apiResourceSubpath,
} from '@/lib/managed/api-paths'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import { generateUUID } from '@/lib/utils/uuid'
import type {
  AgentId,
  CredentialGroupId,
  EnvironmentId,
  MemoryStoreId,
  SessionId,
} from '@/types/entity-id'
import { parseSessionId } from '@/types/entity-id'
import type { Session, SessionEvent, SessionSkillUsage } from '@/types/managed'

import { parseSessionEventListResponse } from './event-response-parsers'
import {
  collectManagedCursorPages,
  parseManagedCursorPage,
  type ManagedCursorPage,
} from './cursor-page'
import {
  buildManagedSessionFileResourceBody,
  buildManagedSessionRepositoryResourceBody,
  type ManagedSessionFileResourceBody,
  type ManagedSessionFileResourceInput,
  type ManagedSessionRepositoryResourceBody,
  type ManagedSessionRepositoryResourceInput,
} from './session-resource-client'
import { parseSessionCreateResponse, parseSessionResponse } from './session-response-parsers'
import { parseSkillUsageListResponse } from './skill-response-parsers'

export interface ManagedSessionMemoryStoreResourceInput {
  memoryStoreId: MemoryStoreId
  access?: string
  instructions?: string
  mountName?: string
}

export interface ManagedSessionCreateInput {
  agentId: AgentId
  title?: string
  environmentId?: EnvironmentId
  credentialGroupIds?: readonly CredentialGroupId[]
  fileResources?: readonly ManagedSessionFileResourceInput[]
  memoryStoreResources?: readonly ManagedSessionMemoryStoreResourceInput[]
  repositoryResources?: readonly ManagedSessionRepositoryResourceInput[]
}

export interface ManagedSessionCreateBody {
  agent: AgentId
  title?: string
  environment_id?: EnvironmentId
  credential_group_ids?: CredentialGroupId[]
  file_resources?: ManagedSessionFileResourceBody[]
  resources?: Array<{
    memory_store_id: MemoryStoreId
    access: string
    instructions?: string
    mount_name?: string
  }>
  repo_resources?: ManagedSessionRepositoryResourceBody[]
}

export interface SessionEventInput {
  type: string
  [key: string]: unknown
}

export interface ManagedSessionEventPageRequest {
  limit?: number
  order?: 'asc' | 'desc'
  cursor?: {
    direction: 'before' | 'after'
    sequence: number
  }
}

export interface ManagedSessionEventPage {
  events: SessionEvent[]
  hasMore: boolean
}

export interface ManagedSessionPageRequest {
  limit?: number
  afterId?: SessionId
  includeArchived?: boolean
}

export interface ManagedSessionPage {
  sessions: Session[]
  hasMore: boolean
  firstId?: SessionId
  lastId?: SessionId
}

const AGENT_SESSION_OPTION_PAGE_SIZE = 100

export function buildManagedSessionCreateBody(
  input: ManagedSessionCreateInput,
): ManagedSessionCreateBody {
  const body: ManagedSessionCreateBody = {
    agent: apiResourceId(input.agentId) as AgentId,
  }
  if (input.title) body.title = input.title
  if (input.environmentId) {
    body.environment_id = apiResourceId(input.environmentId) as EnvironmentId
  }
  if (input.credentialGroupIds?.length) {
    body.credential_group_ids = input.credentialGroupIds.map(
      (id) => apiResourceId(id) as CredentialGroupId,
    )
  }
  if (input.fileResources?.length) {
    body.file_resources = input.fileResources.map(buildManagedSessionFileResourceBody)
  }
  if (input.memoryStoreResources?.length) {
    body.resources = input.memoryStoreResources.map((resource) => ({
      memory_store_id: apiResourceId(resource.memoryStoreId) as MemoryStoreId,
      access: resource.access ?? 'read_write',
      ...(resource.instructions ? { instructions: resource.instructions } : {}),
      ...(resource.mountName ? { mount_name: resource.mountName } : {}),
    }))
  }
  if (input.repositoryResources?.length) {
    body.repo_resources = input.repositoryResources.map(buildManagedSessionRepositoryResourceBody)
  }
  return body
}

export async function createManagedSession(
  input: ManagedSessionCreateInput,
  requestScope: ManagedRequestScope,
): Promise<SessionId> {
  const response = await managedPost<unknown>(
    '/sessions',
    buildManagedSessionCreateBody(input),
    managedRequestOptions(requestScope),
  )
  return parseSessionCreateResponse(response).id
}

export function managedSessionQueryKey(scopeKey: string, sessionId: SessionId) {
  return ['session', scopeKey, sessionId] as const
}

export const MANAGED_SESSIONS_QUERY_ROOT = 'sessions'
export const MANAGED_SESSIONS_SOURCE_KEY = 'managed-session-list'

export function managedSessionsQueryPrefix(scopeKey: string) {
  return [MANAGED_SESSIONS_QUERY_ROOT, scopeKey] as const
}

export function managedAgentSessionsQueryPrefix(scopeKey: string, agentId: AgentId) {
  return ['agent-sessions', scopeKey, agentId] as const
}

export function managedAgentSessionsQueryKey(
  scopeKey: string,
  agentId: AgentId | null,
  request: ManagedSessionPageRequest = {},
) {
  const prefix = agentId
    ? managedAgentSessionsQueryPrefix(scopeKey, agentId)
    : (['agent-sessions', scopeKey, null] as const)
  return [
    ...prefix,
    request.limit ?? 20,
    request.afterId ?? null,
    request.includeArchived ?? false,
  ] as const
}

export function managedAgentSessionOptionsQueryKey(scopeKey: string, agentId: AgentId | null) {
  return ['agent-sessions', scopeKey, agentId, 'options', false] as const
}

export function managedSessionSkillUsageQueryKey(scopeKey: string, sessionId: SessionId) {
  return ['session-skill-usage', scopeKey, sessionId] as const
}

export async function fetchManagedSession(
  sessionId: SessionId,
  requestScope: ManagedRequestScope,
): Promise<Session> {
  const response = await managedGet<unknown>(
    apiResourcePath('sessions', sessionId),
    managedRequestOptions(requestScope),
  )
  return parseSessionResponse(response)
}

export async function fetchManagedAgentSessions(
  agentId: AgentId,
  request: ManagedSessionPageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedSessionPage> {
  const response = await managedGet<unknown>(
    apiResourceSubpath('agents', agentId, ['sessions'], {
      limit: request.limit,
      after_id: request.afterId,
      include_archived: request.includeArchived || undefined,
    }),
    managedRequestOptions(requestScope),
  )
  return parseManagedSessionPage(response, 'Agent Session list response')
}

export async function fetchManagedAgentSessionOptions(
  agentId: AgentId,
  requestScope: ManagedRequestScope,
): Promise<Session[]> {
  const sessions = await collectManagedCursorPages<Session, SessionId>({
    responseName: 'Agent Session options pagination',
    fetchPage: async (afterId) => {
      const page = await fetchManagedAgentSessions(
        agentId,
        { limit: AGENT_SESSION_OPTION_PAGE_SIZE, afterId, includeArchived: false },
        requestScope,
      )
      return {
        items: page.sessions,
        hasMore: page.hasMore,
        firstId: page.firstId,
        lastId: page.lastId,
      }
    },
  })
  return sessions.filter((session) => !session.archived_at)
}

export async function fetchManagedSessions(
  request: ManagedSessionPageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedCursorPage<Session, SessionId>> {
  const response = await managedGet<unknown>(
    apiCollectionPath('sessions', {
      limit: request.limit,
      after_id: request.afterId,
      include_archived: request.includeArchived,
    }),
    managedRequestOptions(requestScope),
  )
  const page = parseManagedSessionPage(response, 'Session list response')
  return {
    items: page.sessions,
    hasMore: page.hasMore,
    firstId: page.firstId,
    lastId: page.lastId,
  }
}

function parseManagedSessionPage(response: unknown, responseName: string): ManagedSessionPage {
  const page = parseManagedCursorPage(response, {
    parseItem: parseSessionResponse,
    parseCursor: parseSessionId,
    responseName,
  })
  return {
    sessions: page.items,
    hasMore: page.hasMore,
    firstId: page.firstId,
    lastId: page.lastId,
  }
}

export async function fetchManagedSessionSkillUsage(
  sessionId: SessionId,
  requestScope: ManagedRequestScope,
): Promise<SessionSkillUsage[]> {
  const response = await managedGet<unknown>(
    apiResourcePath('sessions', sessionId, 'skill-usage'),
    managedRequestOptions(requestScope),
  )
  return parseSkillUsageListResponse(response)
}

export async function fetchManagedSessionEvents(
  sessionId: SessionId,
  request: ManagedSessionEventPageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedSessionEventPage> {
  const query: Record<string, string | number> = {
    limit: request.limit ?? 100,
    order: request.order ?? 'asc',
  }
  if (request.cursor?.direction === 'before') {
    query.before_seq = request.cursor.sequence
  } else if (request.cursor?.direction === 'after') {
    query.after_seq = request.cursor.sequence
  }
  const response = await managedGet<{ data: unknown[]; has_more: boolean }>(
    apiResourceSubpath('sessions', sessionId, ['events'], query),
    managedRequestOptions(requestScope),
  )
  return {
    events: parseSessionEventListResponse(response.data),
    hasMore: response.has_more,
  }
}

export async function appendManagedSessionEvents(
  sessionId: SessionId,
  events: SessionEventInput[],
  requestScope: ManagedRequestScope,
  options: { idempotencyKey?: string } = {},
): Promise<void> {
  const requestOptions = managedRequestOptions(requestScope)
  await managedPost(
    apiResourcePath('sessions', sessionId, 'events'),
    { events },
    options.idempotencyKey
      ? {
          ...requestOptions,
          headers: {
            ...requestOptions.headers,
            'Idempotency-Key': options.idempotencyKey,
          },
        }
      : requestOptions,
  )
}

export function sendManagedSessionUserMessage(
  sessionId: SessionId,
  text: string,
  requestScope: ManagedRequestScope,
): Promise<void> {
  return appendManagedSessionEvents(
    sessionId,
    [{ type: 'user.message', content: [{ type: 'text', text }] }],
    requestScope,
    { idempotencyKey: `session-message:${generateUUID()}` },
  )
}

export async function stopManagedSession(
  sessionId: SessionId,
  requestScope: ManagedRequestScope,
): Promise<void> {
  await managedPost(
    apiResourcePath('sessions', sessionId, 'stop'),
    {},
    managedRequestOptions(requestScope),
  )
}

export async function archiveManagedSession(
  sessionId: SessionId,
  requestScope: ManagedRequestScope,
): Promise<void> {
  await managedPost(
    apiResourcePath('sessions', sessionId, 'archive'),
    {},
    managedRequestOptions(requestScope),
  )
}
