import { objectValue } from '@/lib/managed/quickstart-value-coercion'

export interface QuickstartAcceptanceTest {
  message: string
  checks: string[]
}

export interface QuickstartCapabilityPlanItem {
  name: string
  purpose: string
  whenUsed: string
  skillId: string
  serverUrl: string
}

export interface QuickstartCapabilityPlan {
  skills: QuickstartCapabilityPlanItem[]
  tools: QuickstartCapabilityPlanItem[]
  mcpServers: QuickstartCapabilityPlanItem[]
}

export interface QuickstartAgentBlueprint {
  mission: string
  responsibilities: string[]
  workflow: string[]
  boundaries: string[]
  capabilityPlan: QuickstartCapabilityPlan
  toolPlan: string[]
  escalationConditions: string[]
  outputContract: string[]
  successCriteria: string[]
  acceptanceTest: QuickstartAcceptanceTest
}

function capabilityItems(value: unknown): QuickstartCapabilityPlanItem[] {
  if (!Array.isArray(value)) return []

  return value
    .map((item) => {
      const record = objectValue(item)
      if (!record) return null
      const name = stringValue(record.name)
      if (!name) return null
      return {
        name,
        purpose: stringValue(record.purpose),
        whenUsed: stringValue(field(record, 'whenUsed', 'when_used')),
        skillId: stringValue(field(record, 'skillId', 'skill_id')),
        serverUrl: stringValue(field(record, 'serverUrl', 'server_url')),
      }
    })
    .filter((item): item is QuickstartCapabilityPlanItem => item !== null)
    .slice(0, 12)
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map(stringValue).filter(Boolean).slice(0, 12)
}

function field(
  value: Record<string, unknown> | undefined,
  camelCaseKey: string,
  snakeCaseKey: string,
): unknown {
  return value?.[camelCaseKey] ?? value?.[snakeCaseKey]
}

export function normalizeQuickstartAgentBlueprint(
  agentConfig: Record<string, unknown> | undefined,
): QuickstartAgentBlueprint {
  const blueprint = objectValue(agentConfig?.blueprint)
  const acceptanceTest = objectValue(field(blueprint, 'acceptanceTest', 'acceptance_test'))
  const capabilityPlan = objectValue(field(blueprint, 'capabilityPlan', 'capability_plan'))

  return {
    mission:
      stringValue(blueprint?.mission) ||
      stringValue(agentConfig?.description) ||
      stringValue(agentConfig?.name),
    responsibilities: stringList(blueprint?.responsibilities),
    workflow: stringList(blueprint?.workflow),
    boundaries: stringList(blueprint?.boundaries),
    capabilityPlan: {
      skills: capabilityItems(capabilityPlan?.skills),
      tools: capabilityItems(capabilityPlan?.tools),
      mcpServers: capabilityItems(field(capabilityPlan, 'mcpServers', 'mcp_servers')),
    },
    toolPlan: stringList(field(blueprint, 'toolPlan', 'tool_plan')),
    escalationConditions: stringList(
      field(blueprint, 'escalationConditions', 'escalation_conditions'),
    ),
    outputContract: stringList(field(blueprint, 'outputContract', 'output_contract')),
    successCriteria: stringList(field(blueprint, 'successCriteria', 'success_criteria')),
    acceptanceTest: {
      message: stringValue(acceptanceTest?.message),
      checks: stringList(acceptanceTest?.checks),
    },
  }
}

function hasBlueprintContent(blueprint: QuickstartAgentBlueprint): boolean {
  return Boolean(
    blueprint.mission ||
    blueprint.responsibilities.length ||
    blueprint.workflow.length ||
    blueprint.boundaries.length ||
    blueprint.capabilityPlan.skills.length ||
    blueprint.capabilityPlan.tools.length ||
    blueprint.capabilityPlan.mcpServers.length ||
    blueprint.toolPlan.length ||
    blueprint.escalationConditions.length ||
    blueprint.outputContract.length ||
    blueprint.successCriteria.length ||
    blueprint.acceptanceTest.message ||
    blueprint.acceptanceTest.checks.length,
  )
}

export function quickstartBlueprintMetadata(
  agentConfig: Record<string, unknown> | undefined,
): Record<string, string> {
  if (!objectValue(agentConfig?.blueprint)) return {}
  const blueprint = normalizeQuickstartAgentBlueprint(agentConfig)
  if (!hasBlueprintContent(blueprint)) return {}

  return {
    quickstart_blueprint_version: '2',
    quickstart_blueprint: JSON.stringify(blueprint),
    ...(blueprint.acceptanceTest.message
      ? { quickstart_acceptance_message: blueprint.acceptanceTest.message }
      : {}),
  }
}
