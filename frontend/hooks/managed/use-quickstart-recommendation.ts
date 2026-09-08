'use client'

import { useQuery } from '@tanstack/react-query'

import {
  fetchQuickstartRecommendation,
  type QuickstartRecommendRequestBody,
} from '@/lib/managed/quickstart-recommendation-client'
import type {
  QuickstartEngineReadiness,
  QuickstartExternalToolsReason,
  QuickstartHostReason,
  QuickstartMcpAuthRequirement,
  QuickstartRecommendation,
} from '@/lib/managed/quickstart-recommendation-contract'
import { hasManagedRequestScope, useManagedRequestScope } from '@/lib/managed/request-scope'

export interface QuickstartSecurityDefaults {
  recommendedHosts: string[]
  recommendedMcpServers: Array<{
    name: string
    url: string
    authRequirement: QuickstartMcpAuthRequirement
  }>
  hostReason: QuickstartHostReason
  externalToolsRecommended: boolean
  externalToolsReason: QuickstartExternalToolsReason | 'none'
}

export const EMPTY_SECURITY_DEFAULTS: QuickstartSecurityDefaults = {
  recommendedHosts: [],
  recommendedMcpServers: [],
  hostReason: 'none',
  externalToolsRecommended: false,
  externalToolsReason: 'none',
}

export interface QuickstartEngineDefault {
  engineId: string
  readiness: QuickstartEngineReadiness
  compatibleConnectionCount: number
  recommended: boolean
}

export type QuickstartRecommendationStatus = 'idle' | 'loading' | 'ready' | 'error'

export function mapEngineDefaults(
  recommendation: QuickstartRecommendation | undefined,
): QuickstartEngineDefault[] {
  if (!recommendation || recommendation.phase !== 'understand' || !recommendation.engine) {
    return []
  }
  return recommendation.engine.options.map((option) => ({
    engineId: option.engine_id,
    readiness: option.readiness,
    compatibleConnectionCount: option.compatible_connection_count,
    recommended: option.engine_id === recommendation.engine?.recommended_engine_id,
  }))
}

export function useQuickstartEngineDefaults({
  intent,
  enabled,
}: {
  intent: string
  enabled: boolean
}): {
  options: QuickstartEngineDefault[]
  status: QuickstartRecommendationStatus
  retry: () => void
} {
  const scope = useManagedRequestScope()
  const canQuery = enabled && Boolean(intent.trim()) && hasManagedRequestScope(scope)
  const query = useQuery({
    queryKey: ['quickstart-understand', scope.key, intent],
    queryFn: () => fetchQuickstartRecommendation({ phase: 'understand', intent }, scope),
    enabled: canQuery,
    staleTime: 60_000,
  })
  const status: QuickstartRecommendationStatus = !canQuery
    ? 'idle'
    : query.isError
      ? 'error'
      : query.isLoading
        ? 'loading'
        : 'ready'
  return {
    options: mapEngineDefaults(query.data),
    status,
    retry: () => {
      if (!canQuery) return
      void query.refetch()
    },
  }
}

/** Map a backend QuickstartRecommendation for the secure phase into UI defaults. */
export function mapSecurityDefaults(
  recommendation: QuickstartRecommendation | undefined,
): QuickstartSecurityDefaults {
  if (!recommendation || recommendation.phase !== 'secure') {
    return EMPTY_SECURITY_DEFAULTS
  }
  const environment = recommendation.environment
  const credentialGroup = recommendation.credential_group
  return {
    recommendedHosts: environment?.allowed_hosts ?? [],
    recommendedMcpServers:
      credentialGroup?.mcp_servers.map((server) => ({
        name: server.name,
        url: server.url,
        authRequirement: server.auth_requirement,
      })) ?? [],
    hostReason: environment?.host_reason ?? 'none',
    // The backend only emits a credential_group when external tools are recommended.
    externalToolsRecommended: credentialGroup != null,
    externalToolsReason: credentialGroup?.external_tools_reason ?? 'none',
  }
}

interface UseQuickstartSecurityDefaultsArgs {
  intent: string
  agentConfig?: Record<string, unknown>
  enabled: boolean
}

/**
 * Backend-sourced secure-phase recommendation (sandbox allowlist + external-tool
 * authorization), replacing the duplicated client heuristic so the backend is the
 * single source. Loading and failure remain explicit so the UI never mistakes
 * an unavailable recommendation for a deliberate empty recommendation.
 */
export function useQuickstartSecurityDefaults({
  intent,
  agentConfig,
  enabled,
}: UseQuickstartSecurityDefaultsArgs): {
  defaults: QuickstartSecurityDefaults
  status: QuickstartRecommendationStatus
  retry: () => void
} {
  const scope = useManagedRequestScope()
  const hasRecommendationInput = Boolean(intent.trim()) || agentConfig !== undefined
  const canQuery = enabled && hasRecommendationInput && hasManagedRequestScope(scope)
  const body: QuickstartRecommendRequestBody = {
    phase: 'secure',
    intent,
    agent_context: agentConfig,
  }
  const query = useQuery({
    queryKey: ['quickstart-security', scope.key, intent, JSON.stringify(agentConfig ?? null)],
    queryFn: () => fetchQuickstartRecommendation(body, scope),
    enabled: canQuery,
    staleTime: 60_000,
  })
  const status: QuickstartRecommendationStatus = !canQuery
    ? 'idle'
    : query.isError
      ? 'error'
      : query.isLoading
        ? 'loading'
        : 'ready'
  return {
    defaults: mapSecurityDefaults(query.data),
    status,
    retry: () => {
      if (!canQuery) return
      void query.refetch()
    },
  }
}
