import {
  parseAgentId,
  parseCredentialGroupId,
  parseEnvironmentId,
  parseMemoryStoreId,
  parseOptionalId,
  parseSessionId,
  parseSessionResourceId,
  type EnvironmentId,
  type SessionId,
} from '@/types/entity-id'
import type {
  ModelConnectionSummary,
  Session,
  SessionAgent,
  SessionMemoryStore,
} from '@/types/managed'

import { parseAgentModelResponse } from './agent-response-parsers'
import { parseModelCredentialReference } from './environment-response-parsers'
import { parseSessionRepoResourceResponse } from './file-response-parsers'
import { parseModelConnectionSummaryResponse } from './credential-response-parsers'
import { parseSessionStorageMountResponse } from './storage-mount-response-parsers'

export interface SessionCreateResponse {
  id: SessionId
}

type RawSessionAgent = Omit<
  SessionAgent,
  'id' | 'agent_id' | 'model' | 'model_credential_id' | 'model_connection'
> & {
  id: string
  agent_id?: string
  model?: unknown
  model_credential_id?: string | null
  model_connection?: (Omit<ModelConnectionSummary, 'id'> & { id: string }) | null
}

type RawSession = Omit<
  Session,
  | 'id'
  | 'agent'
  | 'environment_id'
  | 'credential_group_ids'
  | 'resources'
  | 'repo_resources'
  | 'storage_mounts'
> & {
  id: string
  environment_id?: string | null
  agent?: RawSessionAgent
  credential_group_ids?: string[]
  resources?: unknown[]
  repo_resources?: unknown[]
  storage_mounts?: unknown[]
}

function parseSessionMemoryStoreResponse(response: unknown): SessionMemoryStore {
  const raw = response as Omit<SessionMemoryStore, 'id' | 'memory_store_id'> & {
    id: string
    memory_store_id: string
  }
  return {
    ...raw,
    id: parseSessionResourceId(raw.id),
    memory_store_id: parseMemoryStoreId(raw.memory_store_id),
  }
}

function parseSessionAgent(response: RawSessionAgent): SessionAgent {
  const modelCredentialId = parseModelCredentialReference(response)
  return {
    ...response,
    id: parseAgentId(response.id),
    agent_id: response.agent_id === undefined ? undefined : parseAgentId(response.agent_id),
    model: parseAgentModelResponse(response.model),
    model_credential_id: modelCredentialId,
    model_connection: response.model_connection
      ? parseModelConnectionSummaryResponse(response.model_connection)
      : null,
  }
}

export function parseSessionResponse(response: unknown): Session {
  const raw = response as RawSession
  return {
    ...raw,
    id: parseSessionId(raw.id),
    environment_id: parseOptionalId<EnvironmentId>(raw.environment_id, parseEnvironmentId),
    agent: raw.agent === undefined ? undefined : parseSessionAgent(raw.agent),
    credential_group_ids: raw.credential_group_ids?.map(parseCredentialGroupId),
    resources: raw.resources?.map(parseSessionMemoryStoreResponse),
    repo_resources: raw.repo_resources?.map(parseSessionRepoResourceResponse),
    storage_mounts: raw.storage_mounts?.map(parseSessionStorageMountResponse),
  }
}

export function parseSessionCreateResponse(response: unknown): SessionCreateResponse {
  if (typeof response !== 'object' || response === null || Array.isArray(response)) {
    throw new Error('Invalid session create response')
  }
  const raw = response as { id?: unknown }
  if (typeof raw.id !== 'string') {
    throw new Error('Invalid session id')
  }
  return { id: parseSessionId(raw.id) }
}

export function parseSessionListResponse(response: unknown): Session[] {
  return (response as RawSession[]).map(parseSessionResponse)
}
