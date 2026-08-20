import { parseAgentId, parseSkillId } from '@/types/entity-id'
import type {
  Agent,
  AgentModelConfig,
  AgentSkillRef,
  ModelConnectionSummary,
} from '@/types/managed'

import { parseModelConnectionSummaryResponse } from './secret-response-parsers'

type RawAgentSkillRef = Omit<AgentSkillRef, 'skill_id'> & { skill_id: string }

type RawAgent = Omit<Agent, 'id' | 'skills' | 'model' | 'model_connection'> & {
  id: string
  model?: unknown
  skills?: RawAgentSkillRef[]
  model_connection?: (Omit<ModelConnectionSummary, 'id'> & { id: string }) | null
}

export function parseAgentModelResponse(response: unknown): AgentModelConfig | null {
  if (response === null || response === undefined) return null
  if (typeof response !== 'object' || Array.isArray(response)) {
    throw new Error('Invalid agent model')
  }

  const raw = response as { id?: unknown; speed?: unknown }
  if (typeof raw.id !== 'string' || !raw.id.trim()) {
    throw new Error('Invalid agent model id')
  }
  if (raw.speed !== undefined && raw.speed !== null) {
    if (typeof raw.speed !== 'string' || !raw.speed.trim()) {
      throw new Error('Invalid agent model speed')
    }
    return { id: raw.id.trim(), speed: raw.speed.trim() }
  }

  return { id: raw.id.trim() }
}

export function parseAgentResponse(response: unknown): Agent {
  const raw = response as RawAgent
  if (typeof raw.engine_kind !== 'string' || !raw.engine_kind.trim()) {
    throw new Error('Invalid agent engine_kind')
  }
  return {
    ...raw,
    id: parseAgentId(raw.id),
    engine_kind: raw.engine_kind.trim(),
    model: parseAgentModelResponse(raw.model),
    model_connection: raw.model_connection
      ? parseModelConnectionSummaryResponse(raw.model_connection)
      : null,
    skills: raw.skills?.map((skill) => ({ ...skill, skill_id: parseSkillId(skill.skill_id) })),
  }
}

export function parseAgentListResponse(response: unknown): Agent[] {
  return (response as RawAgent[]).map(parseAgentResponse)
}
