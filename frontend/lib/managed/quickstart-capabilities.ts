import type { SessionEvent } from '@/types/managed'

export interface QuickstartSkillCatalogItem {
  id: string
  name: string
  display_title?: string
  description?: string
  latest_version?: string | null
  runtime_eligibility?: { usable?: boolean; reason?: string | null } | null
}

export interface QuickstartAvailableSkill {
  id: string
  name: string
  display_title?: string
  description: string
  latest_version: string
}

export interface QuickstartSkillReference {
  type: 'custom'
  skill_id: string
  version: string
}

export interface QuickstartCapabilityEvidence {
  responseReceived: boolean
  environmentAttached: boolean
  externalToolsAuthorized: boolean
  observedTools: string[]
  observedMcpTools: string[]
  auditEventsAvailable: boolean
}

function nonEmptyString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

export function toQuickstartAvailableSkills(
  skills: QuickstartSkillCatalogItem[],
): QuickstartAvailableSkill[] {
  return skills
    .filter(
      (skill) =>
        Boolean(skill.latest_version) && skill.runtime_eligibility?.usable !== false,
    )
    .slice(0, 20)
    .map((skill) => ({
      id: skill.id,
      name: skill.name,
      ...(skill.display_title ? { display_title: skill.display_title } : {}),
      description: skill.description || '',
      latest_version: skill.latest_version!,
    }))
}

export function filterQuickstartSkillReferences(
  value: unknown,
  allowedSkillIds: ReadonlySet<string>,
): QuickstartSkillReference[] {
  if (!Array.isArray(value)) return []

  const seen = new Set<string>()
  const references: QuickstartSkillReference[] = []
  for (const item of value) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue
    const record = item as Record<string, unknown>
    const skillId = nonEmptyString(record.skill_id)
    if (!skillId || !allowedSkillIds.has(skillId) || seen.has(skillId)) continue
    seen.add(skillId)
    references.push({
      type: 'custom',
      skill_id: skillId,
      version: nonEmptyString(record.version) || 'latest',
    })
  }
  return references
}

function observedName(event: SessionEvent): string {
  return nonEmptyString(event.tool_name) || nonEmptyString(event.tool) || nonEmptyString(event.name)
}

export function deriveQuickstartCapabilityEvidence({
  responseReceived,
  environmentId,
  credentialGroupId,
  events,
}: {
  responseReceived: boolean
  environmentId?: string | null
  credentialGroupId?: string | null
  events: SessionEvent[]
}): QuickstartCapabilityEvidence {
  const observedTools = new Set<string>()
  const observedMcpTools = new Set<string>()

  for (const event of events) {
    const name = observedName(event)
    if (!name) continue
    if (event.type === 'agent.mcp_tool_use' || event.type === 'agent.mcp_tool_result') {
      observedMcpTools.add(name)
    } else if (
      event.type === 'agent.tool_use' ||
      event.type === 'agent.tool_result' ||
      event.type === 'agent.custom_tool_use' ||
      event.type === 'user.custom_tool_result' ||
      event.type === 'user.tool_result'
    ) {
      observedTools.add(name)
    }
  }

  return {
    responseReceived,
    environmentAttached: Boolean(environmentId),
    externalToolsAuthorized: Boolean(credentialGroupId),
    observedTools: Array.from(observedTools),
    observedMcpTools: Array.from(observedMcpTools),
    auditEventsAvailable: events.length > 0,
  }
}
