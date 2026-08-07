import {
  parseEnvironmentId,
  parseSessionId,
  type EnvironmentId,
  type SessionId,
} from '@/types/entity-id'
import type { StorageMountAudit } from '@/types/managed'

type RawStorageMountAudit = Omit<StorageMountAudit, 'session_id' | 'environment_id'> & {
  session_id?: string | null
  environment_id?: string | null
}

function parseOptionalId<T>(
  value: string | null | undefined,
  parse: (raw: string) => T,
): T | null | undefined {
  return value == null ? value : parse(value)
}

export function parseStorageMountAuditResponse(response: unknown): StorageMountAudit {
  const raw = response as RawStorageMountAudit
  return {
    ...raw,
    session_id: parseOptionalId<SessionId>(raw.session_id, parseSessionId),
    environment_id: parseOptionalId<EnvironmentId>(raw.environment_id, parseEnvironmentId),
  }
}
