import { parseAgentId, parseCredentialGroupId, parseSessionId } from '@/types/entity-id'
import type { Session, SessionAgent } from '@/types/managed'
import { parseSessionRepoResourceResponse } from './file-response-parsers'
import { parseSessionStorageMountResponse } from './storage-mount-response-parsers'

type RawSessionAgent = Omit<SessionAgent, 'id' | 'agent_id'> & {
  id: string
  agent_id?: string
}

type RawSession = Omit<
  Session,
  'id' | 'agent' | 'credential_group_ids' | 'repo_resources' | 'storage_mounts'
> & {
  id: string
  agent?: RawSessionAgent
  credential_group_ids?: string[]
  repo_resources?: unknown[]
  storage_mounts?: unknown[]
}

function parseSessionAgent(response: RawSessionAgent): SessionAgent {
  return {
    ...response,
    id: parseAgentId(response.id),
    agent_id: response.agent_id === undefined ? undefined : parseAgentId(response.agent_id),
  }
}

export function parseSessionResponse(response: unknown): Session {
  const raw = response as RawSession
  return {
    ...raw,
    id: parseSessionId(raw.id),
    agent: raw.agent === undefined ? undefined : parseSessionAgent(raw.agent),
    credential_group_ids: raw.credential_group_ids?.map(parseCredentialGroupId),
    repo_resources: raw.repo_resources?.map(parseSessionRepoResourceResponse),
    storage_mounts: raw.storage_mounts?.map(parseSessionStorageMountResponse),
  }
}

export function parseSessionListResponse(response: unknown): Session[] {
  return (response as RawSession[]).map(parseSessionResponse)
}
