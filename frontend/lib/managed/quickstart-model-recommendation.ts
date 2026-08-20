import type { LlmEngineCapability } from '@/types/llm'
import type { Secret } from '@/types/managed'

export type QuickstartModelRecommendationReason =
  | 'onlyCompatible'
  | 'preferredProtocolDefault'
  | 'protocolDefault'
  | 'preferredProtocol'
  | 'recentCompatible'

export interface QuickstartModelRecommendation {
  secret: Secret
  reason: QuickstartModelRecommendationReason
  autoContinue: boolean
}

function createdTime(secret: Secret): number {
  const time = Date.parse(secret.created_at)
  return Number.isFinite(time) ? time : 0
}

function protocolRank(engine: LlmEngineCapability | null | undefined, secret: Secret): number {
  if (!engine || !secret.protocol) return Number.MAX_SAFE_INTEGER
  const preferredIndex = engine.preferred_protocol_ids.indexOf(secret.protocol)
  if (preferredIndex >= 0) return preferredIndex
  const supportedIndex = engine.supported_protocol_ids.indexOf(secret.protocol)
  if (supportedIndex >= 0) return engine.preferred_protocol_ids.length + supportedIndex
  return Number.MAX_SAFE_INTEGER
}

function compareRecommended(
  engine: LlmEngineCapability | null | undefined,
  a: Secret,
  b: Secret,
): number {
  const rankDiff = protocolRank(engine, a) - protocolRank(engine, b)
  if (rankDiff !== 0) return rankDiff
  const createdDiff = createdTime(b) - createdTime(a)
  if (createdDiff !== 0) return createdDiff
  return b.id.localeCompare(a.id)
}

function isPreferredProtocol(
  engine: LlmEngineCapability | null | undefined,
  secret: Secret,
): boolean {
  return Boolean(
    engine && secret.protocol && engine.preferred_protocol_ids.includes(secret.protocol),
  )
}

export function recommendQuickstartModelConnection(
  options: Secret[],
  engine: LlmEngineCapability | null | undefined,
): QuickstartModelRecommendation | null {
  const activeOptions = options.filter((option) => !option.archived_at)
  if (activeOptions.length === 0) return null
  if (activeOptions.length === 1) {
    return {
      secret: activeOptions[0],
      reason: 'onlyCompatible',
      autoContinue: true,
    }
  }

  const defaultOptions = activeOptions.filter((option) => option.is_default)
  if (defaultOptions.length > 0) {
    const secret = [...defaultOptions].sort((a, b) => compareRecommended(engine, a, b))[0]
    return {
      secret,
      reason: isPreferredProtocol(engine, secret) ? 'preferredProtocolDefault' : 'protocolDefault',
      autoContinue: true,
    }
  }

  const preferredOptions = activeOptions.filter((option) => isPreferredProtocol(engine, option))
  if (preferredOptions.length > 0) {
    const secret = [...preferredOptions].sort((a, b) => compareRecommended(engine, a, b))[0]
    return {
      secret,
      reason: 'preferredProtocol',
      autoContinue: false,
    }
  }

  return {
    secret: [...activeOptions].sort((a, b) => compareRecommended(engine, a, b))[0],
    reason: 'recentCompatible',
    autoContinue: false,
  }
}
