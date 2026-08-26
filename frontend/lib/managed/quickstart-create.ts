import { normalizeMcpServerConfigs } from '@/lib/managed/mcp-config'
import { quickstartBlueprintMetadata } from '@/lib/managed/quickstart-agent-blueprint'
import { filterQuickstartSkillReferences } from '@/lib/managed/quickstart-capabilities'
import { objectValue } from '@/lib/managed/quickstart-value-coercion'
import type { CredentialId, SkillId } from '@/types/entity-id'

type AgentCreateOptions = {
  engineKind: string
  modelCredentialId: CredentialId
  suffix: string
  allowedSkillIds?: ReadonlySet<SkillId>
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function arrayValue(value: unknown): unknown[] | undefined {
  return Array.isArray(value) ? value : undefined
}

// The quickstart wizard fills these fields from model-generated config, whose
// shape is not guaranteed. The backend types them strictly (env/metadata are
// dict[str, str]; model is {id: str, speed?: str}), so an int/nested value or a
// model object missing `id` would 422 the whole agent-create request. Coerce
// what we safely can and drop what we can't, rather than forwarding raw.

function scalarString(value: unknown): string | undefined {
  if (typeof value === 'string') return value
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  if (typeof value === 'boolean') return String(value)
  return undefined
}

function stringMap(value: unknown): Record<string, string> | undefined {
  const obj = objectValue(value)
  if (!obj) return undefined
  const out: Record<string, string> = {}
  for (const [key, raw] of Object.entries(obj)) {
    const coerced = scalarString(raw)
    if (coerced !== undefined) out[key] = coerced
  }
  return Object.keys(out).length ? out : undefined
}

function modelValue(value: unknown): string | Record<string, string> | undefined {
  const asString = nonEmptyString(value)
  if (asString) return asString

  const obj = objectValue(value)
  if (!obj) return undefined

  const id = nonEmptyString(obj.id)
  if (!id) return undefined

  const speed = nonEmptyString(obj.speed)
  return speed ? { id, speed } : { id }
}

export function buildQuickstartAgentCreateBody(
  agentConfig: Record<string, unknown>,
  options: AgentCreateOptions,
): Record<string, unknown> {
  const name = nonEmptyString(agentConfig.name) || 'Untitled Agent'
  const systemPrompt = nonEmptyString(agentConfig.system)

  const body: Record<string, unknown> = {
    name: `${name}${options.suffix}`,
    engine_kind: options.engineKind,
    system: systemPrompt || null,
    model_credential_id: options.modelCredentialId,
    tools: arrayValue(agentConfig.tools) || [],
  }

  const description = nonEmptyString(agentConfig.description)
  if (description) body.description = description

  const model = modelValue(agentConfig.model)
  if (model) body.model = model

  const metadata = {
    ...(stringMap(agentConfig.metadata) || {}),
    ...quickstartBlueprintMetadata(agentConfig),
  }
  if (Object.keys(metadata).length > 0) body.metadata = metadata

  const mcpServers = arrayValue(agentConfig.mcp_servers)
  if (mcpServers) body.mcp_servers = normalizeMcpServerConfigs(mcpServers)

  const skills = options.allowedSkillIds
    ? filterQuickstartSkillReferences(agentConfig.skills, options.allowedSkillIds)
    : arrayValue(agentConfig.skills)
  if (skills) body.skills = skills

  const env = stringMap(agentConfig.env)
  if (env) body.env = env

  const multiagent = objectValue(agentConfig.multiagent)
  if (multiagent) body.multiagent = multiagent

  return body
}
