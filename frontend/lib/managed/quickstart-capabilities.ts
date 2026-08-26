import type { SessionEvent } from '@/types/managed'
import { parseSkillId, type SkillId } from '@/types/entity-id'

import { normalizeMcpServerUrl } from './mcp-credential-coverage'

export { normalizeMcpServerUrl } from './mcp-credential-coverage'

export interface QuickstartSkillCatalogItem {
  id: SkillId
  name: string
  display_title?: string
  description?: string
  latest_version?: string | null
}

export interface QuickstartAvailableSkill {
  id: SkillId
  name: string
  display_title?: string
  description: string
  latest_version: string
}

export interface QuickstartSkillReference {
  type: 'custom'
  skill_id: SkillId
  version: string
}

export interface QuickstartCapabilityEvidence {
  responseReceived: boolean
  environmentAttached: boolean
  externalToolsAuthorized: boolean
  configuredSkills: string[]
  observedTools: string[]
  observedMcpTools: string[]
  auditEventsAvailable: boolean
}

function nonEmptyString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

export function quickstartAuthorizedMcpServerUrls(
  members: { mcp_server_url?: string | null; archived_at?: string | null }[],
): Set<string> {
  const urls = new Set<string>()
  for (const member of members) {
    if (member.archived_at) continue
    const normalized = normalizeMcpServerUrl(member.mcp_server_url)
    if (normalized) urls.add(normalized)
  }
  return urls
}

export function isMcpServerAuthorized(url: unknown, authorizedUrls: ReadonlySet<string>): boolean {
  const normalized = normalizeMcpServerUrl(url)
  if (!normalized) return false
  return authorizedUrls.has(normalized)
}

export function toQuickstartAvailableSkills(
  skills: QuickstartSkillCatalogItem[],
): QuickstartAvailableSkill[] {
  return skills
    .filter((skill) => Boolean(skill.latest_version))
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
  allowedSkillIds: ReadonlySet<SkillId>,
): QuickstartSkillReference[] {
  if (!Array.isArray(value)) return []

  const seen = new Set<string>()
  const references: QuickstartSkillReference[] = []
  for (const item of value) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue
    const record = item as Record<string, unknown>
    const rawSkillId = nonEmptyString(record.skill_id)
    if (!rawSkillId) continue
    let skillId: SkillId
    try {
      skillId = parseSkillId(rawSkillId)
    } catch {
      continue
    }
    if (!allowedSkillIds.has(skillId) || seen.has(skillId)) continue
    seen.add(skillId)
    references.push({
      type: 'custom',
      skill_id: skillId,
      version: nonEmptyString(record.version) || 'latest',
    })
  }
  return references
}

export function quickstartConfiguredSkillNames(
  agentConfig: Record<string, unknown> | undefined,
  availableSkills: QuickstartAvailableSkill[],
): string[] {
  const allowedIds = new Set(availableSkills.map((skill) => skill.id))
  const references = filterQuickstartSkillReferences(agentConfig?.skills, allowedIds)
  const namesById = new Map(
    availableSkills.map((skill) => [skill.id, skill.display_title || skill.name]),
  )
  return references.map((reference) => namesById.get(reference.skill_id) || reference.skill_id)
}

function observedName(event: SessionEvent): string {
  return nonEmptyString(event.tool_name) || nonEmptyString(event.tool) || nonEmptyString(event.name)
}

export function deriveQuickstartCapabilityEvidence({
  responseReceived,
  environmentId,
  externalToolsAuthorized = false,
  configuredSkills = [],
  events,
}: {
  responseReceived: boolean
  environmentId?: string | null
  externalToolsAuthorized?: boolean
  configuredSkills?: string[]
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
    externalToolsAuthorized,
    configuredSkills: Array.from(new Set(configuredSkills.filter(Boolean))),
    observedTools: Array.from(observedTools),
    observedMcpTools: Array.from(observedMcpTools),
    auditEventsAvailable: events.length > 0,
  }
}
