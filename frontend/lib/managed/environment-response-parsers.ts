import { parseEnvironmentId } from '@/types/entity-id'
import type { Environment } from '@/types/managed'

type RawEnvironment = Omit<Environment, 'id'> & { id: string }

export function parseEnvironmentResponse(response: unknown): Environment {
  const raw = response as RawEnvironment
  return { ...raw, id: parseEnvironmentId(raw.id) }
}

export function parseEnvironmentListResponse(response: RawEnvironment[]): Environment[] {
  return response.map(parseEnvironmentResponse)
}
