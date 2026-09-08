import { managedGet } from '@/lib/api-client'
import { apiCollectionPath, apiResourcePath, apiResourceSubpath } from '@/lib/managed/api-paths'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import { parseAgentId, type AgentId } from '@/types/entity-id'
import type { Agent, AgentVersion } from '@/types/managed'

import { parseAgentResponse, parseAgentVersionListResponse } from './agent-response-parsers'
import {
  collectManagedCursorPages,
  parseManagedCursorPage,
  type ManagedCursorPage,
} from './cursor-page'

const AGENT_OPTION_PAGE_SIZE = 100
const AGENT_VERSION_PAGE_SIZE = 100

export interface ManagedAgentPageRequest {
  limit?: number
  afterId?: AgentId
  includeArchived?: boolean
}

export interface ManagedAgentVersionPageRequest {
  limit?: number
  beforeVersion?: number
}

export interface ManagedAgentVersionPage {
  versions: AgentVersion[]
  hasMore: boolean
}

export const MANAGED_AGENTS_QUERY_ROOT = 'agents'
export const MANAGED_AGENTS_SOURCE_KEY = 'managed-agent-list'

export function managedAgentListQueryPrefix(scopeKey: string) {
  return [MANAGED_AGENTS_QUERY_ROOT, scopeKey, MANAGED_AGENTS_SOURCE_KEY] as const
}

export function managedAgentOptionsQueryKey(scopeKey: string) {
  return [MANAGED_AGENTS_QUERY_ROOT, scopeKey, 'options', false] as const
}

export function managedAgentQueryKey(scopeKey: string, agentId: AgentId | null) {
  return ['agent', scopeKey, agentId] as const
}

export function managedAgentVersionsQueryKey(scopeKey: string, agentId: AgentId | null) {
  return ['agent-versions', scopeKey, agentId] as const
}

export async function fetchManagedAgent(
  agentId: AgentId,
  requestScope: ManagedRequestScope,
): Promise<Agent> {
  const response = await managedGet<unknown>(
    apiResourcePath('agents', agentId),
    managedRequestOptions(requestScope),
  )
  return parseAgentResponse(response)
}

export async function fetchManagedAgentVersions(
  agentId: AgentId,
  request: ManagedAgentVersionPageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedAgentVersionPage> {
  const response = await managedGet<unknown>(
    apiResourceSubpath('agents', agentId, ['versions'], {
      limit: request.limit,
      before_version: request.beforeVersion,
    }),
    managedRequestOptions(requestScope),
  )
  if (!response || typeof response !== 'object' || Array.isArray(response)) {
    throw new Error('Invalid Agent version list response')
  }
  const raw = response as { data?: unknown; has_more?: unknown }
  if (!Array.isArray(raw.data) || typeof raw.has_more !== 'boolean') {
    throw new Error('Invalid Agent version list response')
  }
  return {
    versions: parseAgentVersionListResponse(raw.data),
    hasMore: raw.has_more,
  }
}

export async function fetchManagedAgentVersionHistory(
  agentId: AgentId,
  requestScope: ManagedRequestScope,
): Promise<AgentVersion[]> {
  const versions: AgentVersion[] = []
  const seenVersions = new Set<number>()
  let beforeVersion: number | undefined

  for (;;) {
    const page = await fetchManagedAgentVersions(
      agentId,
      { limit: AGENT_VERSION_PAGE_SIZE, beforeVersion },
      requestScope,
    )
    versions.push(...page.versions)
    if (!page.hasMore) return versions

    const nextBeforeVersion = page.versions.at(-1)?.version
    if (
      nextBeforeVersion === undefined ||
      nextBeforeVersion === beforeVersion ||
      seenVersions.has(nextBeforeVersion)
    ) {
      throw new Error('Agent version history returned an invalid cursor')
    }
    seenVersions.add(nextBeforeVersion)
    beforeVersion = nextBeforeVersion
  }
}

export async function fetchManagedAgents(
  request: ManagedAgentPageRequest,
  requestScope: ManagedRequestScope,
): Promise<ManagedCursorPage<Agent, AgentId>> {
  const response = await managedGet<unknown>(
    apiCollectionPath('agents', {
      limit: request.limit,
      after_id: request.afterId,
      include_archived: request.includeArchived,
    }),
    managedRequestOptions(requestScope),
  )
  return parseManagedCursorPage(response, {
    parseItem: parseAgentResponse,
    parseCursor: parseAgentId,
    responseName: 'Agent list response',
  })
}

export async function fetchManagedAgentOptions(
  requestScope: ManagedRequestScope,
): Promise<Agent[]> {
  const agents = await collectManagedCursorPages<Agent, AgentId>({
    responseName: 'Agent options pagination',
    fetchPage: (afterId) =>
      fetchManagedAgents(
        {
          limit: AGENT_OPTION_PAGE_SIZE,
          afterId,
          includeArchived: false,
        },
        requestScope,
      ),
  })
  return agents.filter((agent) => !agent.archived_at)
}
