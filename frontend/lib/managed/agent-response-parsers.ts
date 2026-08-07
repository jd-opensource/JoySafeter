import { parseAgentId, parseSkillId } from '@/types/entity-id'
import type { Agent, AgentSkillRef } from '@/types/managed'

type RawAgentSkillRef = Omit<AgentSkillRef, 'skill_id'> & { skill_id: string }

type RawAgent = Omit<Agent, 'id' | 'skills'> & {
  id: string
  skills?: RawAgentSkillRef[]
}

export function parseAgentResponse(response: unknown): Agent {
  const raw = response as RawAgent
  return {
    ...raw,
    id: parseAgentId(raw.id),
    skills: raw.skills?.map((skill) => ({ ...skill, skill_id: parseSkillId(skill.skill_id) })),
  }
}

export function parseAgentListResponse(response: unknown): Agent[] {
  return (response as RawAgent[]).map(parseAgentResponse)
}
