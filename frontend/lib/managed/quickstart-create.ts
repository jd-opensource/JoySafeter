type AgentCreateOptions = {
  engineKind: string
  secretRef: string
  suffix: string
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function objectValue(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  return value as Record<string, unknown>
}

function arrayValue(value: unknown): unknown[] | undefined {
  return Array.isArray(value) ? value : undefined
}

export function buildQuickstartAgentCreateBody(
  agentConfig: Record<string, unknown>,
  options: AgentCreateOptions,
): Record<string, unknown> {
  const name = nonEmptyString(agentConfig.name) || 'Untitled Agent'
  const systemPrompt = nonEmptyString(agentConfig.system_prompt) || nonEmptyString(agentConfig.system)

  const body: Record<string, unknown> = {
    name: `${name}${options.suffix}`,
    engine_kind: options.engineKind,
    system_prompt: systemPrompt || null,
    secret_ref: options.secretRef,
    tools: arrayValue(agentConfig.tools) || [],
  }

  const description = nonEmptyString(agentConfig.description)
  if (description) body.description = description

  const model = nonEmptyString(agentConfig.model) || objectValue(agentConfig.model)
  if (model) body.model = model

  const metadata = objectValue(agentConfig.metadata)
  if (metadata) body.metadata = metadata

  const mcpServers = arrayValue(agentConfig.mcp_servers)
  if (mcpServers) body.mcp_servers = mcpServers

  const skills = arrayValue(agentConfig.skills)
  if (skills) body.skills = skills

  const env = objectValue(agentConfig.env)
  if (env) body.env = env

  const multiagent = objectValue(agentConfig.multiagent)
  if (multiagent) body.multiagent = multiagent

  return body
}
