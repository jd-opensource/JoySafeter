import {
  parseAgentId,
  parseAgentVersionId,
  parseEnvironmentId,
  parseOptionalId,
  parseSkillId,
  type AgentId,
  type EnvironmentId,
} from '@/types/entity-id'
import type {
  Agent,
  AgentModelConfig,
  AgentSkillRef,
  AgentVersion,
  ModelConnectionSummary,
} from '@/types/managed'

import { parseModelConnectionSummaryResponse } from './credential-response-parsers'
import { parseMcpServerResponseConfigs } from './mcp-config'

export interface AgentCreateResponse {
  id: AgentId
}

type RawAgentSkillRef = Omit<AgentSkillRef, 'skill_id'> & { skill_id: string }

type RawAgent = Omit<Agent, 'id' | 'skills' | 'model' | 'model_connection' | 'environment_id'> & {
  id: string
  environment_id?: string | null
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
    environment_id: parseOptionalId<EnvironmentId>(raw.environment_id, parseEnvironmentId),
    engine_kind: raw.engine_kind.trim(),
    model: parseAgentModelResponse(raw.model),
    model_connection: raw.model_connection
      ? parseModelConnectionSummaryResponse(raw.model_connection)
      : null,
    mcp_servers: parseMcpServerResponseConfigs(raw.mcp_servers),
    skills: raw.skills?.map((skill) => ({ ...skill, skill_id: parseSkillId(skill.skill_id) })),
  }
}

export function parseAgentCreateResponse(response: unknown): AgentCreateResponse {
  if (typeof response !== 'object' || response === null || Array.isArray(response)) {
    throw new Error('Invalid agent create response')
  }
  const raw = response as { id?: unknown }
  if (typeof raw.id !== 'string') {
    throw new Error('Invalid agent id')
  }
  return { id: parseAgentId(raw.id) }
}

export function parseAgentListResponse(response: unknown): Agent[] {
  return (response as RawAgent[]).map(parseAgentResponse)
}

type RawAgentVersion = Omit<AgentVersion, 'id' | 'agent_id' | 'snapshot'> & {
  id: string
  agent_id: string
  snapshot: unknown
}

export function parseAgentVersionResponse(response: unknown): AgentVersion {
  const raw = response as RawAgentVersion
  return {
    ...raw,
    id: parseAgentVersionId(raw.id),
    agent_id: parseAgentId(raw.agent_id),
    snapshot: parseAgentResponse(raw.snapshot),
  }
}

export function parseAgentVersionListResponse(response: unknown[]): AgentVersion[] {
  return response.map(parseAgentVersionResponse)
}
