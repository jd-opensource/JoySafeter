import {
  parseAgentId,
  parseOptionalId,
  parseSessionId,
  parseSkillFileId,
  parseSkillId,
  parseSkillSecurityScanId,
  parseSkillUsageId,
  parseSkillVersionFileId,
  parseSkillVersionId,
  type AgentId,
  type SessionId,
  type SkillId,
  type SkillSecurityScanId,
  type SkillVersionId,
} from '@/types/entity-id'
import { parseCollection } from './parse-collection'
import type {
  SessionSkillUsage,
  SkillFileRecord,
  SkillRecord,
  SkillSecurityScanRecord,
  SkillSecurityScanSummary,
  SkillVersionFileRecord,
  SkillVersionRecord,
} from '@/types/managed'

export type SkillAuthoringSaveResponse = {
  skill_id?: SkillId
  created?: boolean
  error?: string
  code?: string
}

export type SkillLifecycleTransitionResponse = {
  skill_id: SkillId
  from_status: string
  to_status: string
}

type RawSkillSecurityScanSummary = Omit<SkillSecurityScanSummary, 'scan_id'> & {
  scan_id: string | null
}

type RawSkillRecord = Omit<
  SkillRecord,
  'id' | 'org_version_id' | 'public_version_id' | 'security_scan'
> & {
  id: string
  org_version_id?: string | null
  public_version_id?: string | null
  security_scan?: RawSkillSecurityScanSummary
}

type RawSkillFileRecord = Omit<SkillFileRecord, 'id' | 'skill_id' | 'content'> & {
  id: string
  skill_id: string
  content: string | null
}

type RawSkillVersionRecord = Omit<SkillVersionRecord, 'id' | 'skill_id'> & {
  id: string
  skill_id: string
}

type RawSkillVersionFileRecord = Omit<SkillVersionFileRecord, 'id' | 'version_id' | 'content'> & {
  id: string
  version_id: string
  content: string | null
}

type RawSkillSecurityScanRecord = Omit<SkillSecurityScanRecord, 'id' | 'skill_id'> & {
  id: string
  skill_id: string | null
}

type RawSessionSkillUsage = Omit<
  SessionSkillUsage,
  'id' | 'skill_id' | 'skill_version_id' | 'security_scan_id' | 'session_id' | 'agent_id'
> & {
  id: string
  skill_id?: string | null
  skill_version_id?: string | null
  security_scan_id?: string | null
  session_id?: string | null
  agent_id?: string | null
}

type RawSkillAuthoringSaveResponse = Omit<SkillAuthoringSaveResponse, 'skill_id'> & {
  skill_id?: string
}

type RawSkillLifecycleTransitionResponse = Omit<SkillLifecycleTransitionResponse, 'skill_id'> & {
  skill_id: string
}

function parseSecuritySummary(summary: RawSkillSecurityScanSummary): SkillSecurityScanSummary {
  return {
    ...summary,
    scan_id:
      parseOptionalId<SkillSecurityScanId>(summary.scan_id, parseSkillSecurityScanId) ?? null,
  }
}

export function parseSkillResponse(response: unknown): SkillRecord {
  const raw = response as RawSkillRecord
  return {
    ...raw,
    id: parseSkillId(raw.id),
    org_version_id: parseOptionalId<SkillVersionId>(raw.org_version_id, parseSkillVersionId),
    public_version_id: parseOptionalId<SkillVersionId>(raw.public_version_id, parseSkillVersionId),
    security_scan: raw.security_scan ? parseSecuritySummary(raw.security_scan) : raw.security_scan,
  }
}

export function parseSkillFileResponse(response: unknown): SkillFileRecord {
  const raw = response as RawSkillFileRecord
  return {
    ...raw,
    id: parseSkillFileId(raw.id),
    skill_id: parseSkillId(raw.skill_id),
    content: raw.content ?? '',
  }
}

export function parseSkillFileListResponse(response: unknown): SkillFileRecord[] {
  return parseCollection(response, parseSkillFileResponse)
}

export function parseSkillVersionResponse(response: unknown): SkillVersionRecord {
  const raw = response as RawSkillVersionRecord
  return {
    ...raw,
    id: parseSkillVersionId(raw.id),
    skill_id: parseSkillId(raw.skill_id),
  }
}

export function parseSkillVersionListResponse(response: unknown): SkillVersionRecord[] {
  return parseCollection(response, parseSkillVersionResponse)
}

export function parseSkillVersionFileResponse(response: unknown): SkillVersionFileRecord {
  const raw = response as RawSkillVersionFileRecord
  return {
    ...raw,
    id: parseSkillVersionFileId(raw.id),
    version_id: parseSkillVersionId(raw.version_id),
    content: raw.content ?? '',
  }
}

export function parseSkillVersionFileListResponse(response: unknown): SkillVersionFileRecord[] {
  return parseCollection(response, parseSkillVersionFileResponse)
}

export function parseSkillSecurityScanResponse(response: unknown): SkillSecurityScanRecord {
  const raw = response as RawSkillSecurityScanRecord
  return {
    ...raw,
    id: parseSkillSecurityScanId(raw.id),
    skill_id: parseOptionalId<SkillId>(raw.skill_id, parseSkillId) ?? null,
  }
}

export function parseSkillSecurityScanListResponse(response: unknown): SkillSecurityScanRecord[] {
  return parseCollection(response, parseSkillSecurityScanResponse)
}

export function parseSkillUsageResponse(response: unknown): SessionSkillUsage {
  const raw = response as RawSessionSkillUsage
  return {
    ...raw,
    id: parseSkillUsageId(raw.id),
    skill_id: parseOptionalId<SkillId>(raw.skill_id, parseSkillId),
    skill_version_id: parseOptionalId<SkillVersionId>(raw.skill_version_id, parseSkillVersionId),
    security_scan_id: parseOptionalId<SkillSecurityScanId>(
      raw.security_scan_id,
      parseSkillSecurityScanId,
    ),
    session_id: parseOptionalId<SessionId>(raw.session_id, parseSessionId),
    agent_id: parseOptionalId<AgentId>(raw.agent_id, parseAgentId),
  }
}

export function parseSkillUsageListResponse(response: unknown): SessionSkillUsage[] {
  return parseCollection(response, parseSkillUsageResponse)
}

export function parseSkillAuthoringSaveResponse(response: unknown): SkillAuthoringSaveResponse {
  const raw = response as RawSkillAuthoringSaveResponse
  return {
    ...raw,
    skill_id: raw.skill_id === undefined ? undefined : parseSkillId(raw.skill_id),
  }
}

export function parseSkillLifecycleTransitionResponse(
  response: unknown,
): SkillLifecycleTransitionResponse {
  const raw = response as RawSkillLifecycleTransitionResponse
  return { ...raw, skill_id: parseSkillId(raw.skill_id) }
}
