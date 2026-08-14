import { parseAgentId, parseSkillId } from '@/types/entity-id'
import type { Agent, AgentSkillRef } from '@/types/managed'

type RawAgentSkillRef = Omit<AgentSkillRef, 'skill_id'> & { skill_id: string }

type RawAgent = Omit<Agent, 'id' | 'skills'> & {
  id: string
  skills?: RawAgentSkillRef[]
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
    skills: raw.skills?.map((skill) => ({ ...skill, skill_id: parseSkillId(skill.skill_id) })),
  }
}

export function parseAgentListResponse(response: unknown): Agent[] {
  return (response as RawAgent[]).map(parseAgentResponse)
}
