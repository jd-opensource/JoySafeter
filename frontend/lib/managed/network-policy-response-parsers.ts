import {
  parseSandboxId,
  parseSessionId,
  parseTaskId,
  type SessionId,
  type TaskId,
} from '@/types/entity-id'
import type { NetworkPolicyListResponse, NetworkPolicyStatus } from '@/types/managed'

type RawNetworkPolicyStatus = Omit<NetworkPolicyStatus, 'sandbox_id' | 'session_id' | 'task_id'> & {
  sandbox_id: string
  session_id?: string | null
  task_id?: string | null
}

type RawNetworkPolicyListResponse = Omit<NetworkPolicyListResponse, 'data'> & {
  data: RawNetworkPolicyStatus[]
}

function parseOptionalId<T>(
  value: string | null | undefined,
  parse: (raw: string) => T,
): T | null | undefined {
  return value == null ? value : parse(value)
}

export function parseNetworkPolicyStatusResponse(response: unknown): NetworkPolicyStatus {
  const raw = response as RawNetworkPolicyStatus
  return {
    ...raw,
    sandbox_id: parseSandboxId(raw.sandbox_id),
    session_id: parseOptionalId<SessionId>(raw.session_id, parseSessionId),
    task_id: parseOptionalId<TaskId>(raw.task_id, parseTaskId),
  }
}

export function parseNetworkPolicyListResponse(response: unknown): NetworkPolicyListResponse {
  const raw = response as RawNetworkPolicyListResponse
  return {
    ...raw,
    data: raw.data.map(parseNetworkPolicyStatusResponse),
  }
}
