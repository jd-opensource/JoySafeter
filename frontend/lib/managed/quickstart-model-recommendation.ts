import type { LlmEngineCapability } from '@/types/llm'
import type { Credential } from '@/types/managed'

export type QuickstartModelRecommendationReason =
  | 'onlyCompatible'
  | 'preferredProtocolDefault'
  | 'protocolDefault'
  | 'preferredProtocol'
  | 'recentCompatible'

export interface QuickstartModelRecommendation {
  credential: Credential
  reason: QuickstartModelRecommendationReason
  autoContinue: boolean
}

function createdTime(credential: Credential): number {
  const time = Date.parse(credential.created_at)
  return Number.isFinite(time) ? time : 0
}

function protocolRank(
  engine: LlmEngineCapability | null | undefined,
  credential: Credential,
): number {
  if (!engine || !credential.protocol) return Number.MAX_SAFE_INTEGER
  const preferredIndex = engine.preferred_protocol_ids.indexOf(credential.protocol)
  if (preferredIndex >= 0) return preferredIndex
  const supportedIndex = engine.supported_protocol_ids.indexOf(credential.protocol)
  if (supportedIndex >= 0) return engine.preferred_protocol_ids.length + supportedIndex
  return Number.MAX_SAFE_INTEGER
}

function compareRecommended(
  engine: LlmEngineCapability | null | undefined,
  a: Credential,
  b: Credential,
): number {
  const rankDiff = protocolRank(engine, a) - protocolRank(engine, b)
  if (rankDiff !== 0) return rankDiff
  const createdDiff = createdTime(b) - createdTime(a)
  if (createdDiff !== 0) return createdDiff
  return b.id.localeCompare(a.id)
}

function isPreferredProtocol(
  engine: LlmEngineCapability | null | undefined,
  credential: Credential,
): boolean {
  return Boolean(
    engine && credential.protocol && engine.preferred_protocol_ids.includes(credential.protocol),
  )
}

export function recommendQuickstartModelConnection(
  options: Credential[],
  engine: LlmEngineCapability | null | undefined,
): QuickstartModelRecommendation | null {
  const activeOptions = options.filter((option) => !option.archived_at)
  if (activeOptions.length === 0) return null
  if (activeOptions.length === 1) {
    return {
      credential: activeOptions[0],
      reason: 'onlyCompatible',
      autoContinue: true,
    }
  }

  const defaultOptions = activeOptions.filter((option) => option.is_default)
  if (defaultOptions.length > 0) {
    const credential = [...defaultOptions].sort((a, b) => compareRecommended(engine, a, b))[0]
    return {
      credential,
      reason: isPreferredProtocol(engine, credential)
        ? 'preferredProtocolDefault'
        : 'protocolDefault',
      autoContinue: true,
    }
  }

  const preferredOptions = activeOptions.filter((option) => isPreferredProtocol(engine, option))
  if (preferredOptions.length > 0) {
    const credential = [...preferredOptions].sort((a, b) => compareRecommended(engine, a, b))[0]
    return {
      credential,
      reason: 'preferredProtocol',
      autoContinue: false,
    }
  }

  return {
    credential: [...activeOptions].sort((a, b) => compareRecommended(engine, a, b))[0],
    reason: 'recentCompatible',
    autoContinue: false,
  }
}
