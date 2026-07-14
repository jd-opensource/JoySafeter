/**
 * React Query hooks for analytics data fetching.
 * All hooks accept AnalyticsFilters and return TanStack Query results.
 */

import { useQuery } from '@tanstack/react-query'
import { managedGet } from '@/lib/api-client'
import type {
  AnalyticsFilters,
  AnalyticsSummary,
  CallsTimePoint,
  TokensTimePoint,
  LatencyTimePoint,
  EngineShareItem,
  CallsListResponse,
  ObservationNode,
  AgentMetrics,
  AgentTrendPoint,
  HealthCheckResponse,
  AlertConfig,
  ErrorSummary,
  LatencyStats,
  AgentRankingItem,
  HeatmapCell,
} from './types'

function buildFilterParams(filters: AnalyticsFilters): Record<string, string> {
  const params: Record<string, string> = { range: filters.range }
  if (filters.engine) params.engine = filters.engine
  if (filters.model) params.model = filters.model
  if (filters.status) params.status = filters.status
  if (filters.agent_id) params.agent_id = filters.agent_id
  return params
}

function toQueryString(params: Record<string, string>): string {
  const qs = new URLSearchParams(params).toString()
  return qs ? `?${qs}` : ''
}

// --- Summary KPIs ---

export function useAnalyticsSummary(filters: AnalyticsFilters) {
  const params = buildFilterParams(filters)
  return useQuery<AnalyticsSummary>({
    queryKey: ['analytics', 'summary', params],
    queryFn: () => managedGet(`/analytics/summary${toQueryString(params)}`),
    staleTime: 60_000,
    refetchInterval: 60_000,
  })
}

// --- Time Series ---

export function useCallsTimeseries(filters: AnalyticsFilters) {
  const params = { ...buildFilterParams(filters), metric: 'calls' }
  return useQuery<CallsTimePoint[]>({
    queryKey: ['analytics', 'timeseries', 'calls', params],
    queryFn: () => managedGet(`/analytics/timeseries${toQueryString(params)}`),
    staleTime: 60_000,
  })
}

export function useTokensTimeseries(filters: AnalyticsFilters) {
  const params = { ...buildFilterParams(filters), metric: 'tokens' }
  return useQuery<TokensTimePoint[]>({
    queryKey: ['analytics', 'timeseries', 'tokens', params],
    queryFn: () => managedGet(`/analytics/timeseries${toQueryString(params)}`),
    staleTime: 60_000,
  })
}

export function useLatencyTimeseries(filters: AnalyticsFilters) {
  const params = { ...buildFilterParams(filters), metric: 'latency' }
  return useQuery<LatencyTimePoint[]>({
    queryKey: ['analytics', 'timeseries', 'latency', params],
    queryFn: () => managedGet(`/analytics/timeseries${toQueryString(params)}`),
    staleTime: 60_000,
  })
}

// --- Engine Share ---

export function useEngineShare(filters: AnalyticsFilters) {
  const params = buildFilterParams(filters)
  return useQuery<EngineShareItem[]>({
    queryKey: ['analytics', 'engine-share', params],
    queryFn: () => managedGet(`/analytics/engine-share${toQueryString(params)}`),
    staleTime: 60_000,
  })
}

// --- Call Records ---

export function useCallsList(
  filters: AnalyticsFilters,
  page: number,
  pageSize: number,
) {
  const params = {
    ...buildFilterParams(filters),
    page: String(page),
    page_size: String(pageSize),
  }
  return useQuery<CallsListResponse>({
    queryKey: ['analytics', 'calls', params],
    queryFn: () => managedGet(`/analytics/calls${toQueryString(params)}`),
    staleTime: 30_000,
  })
}

// --- Observation Tree ---

export function useObservationTree(traceId: string | null) {
  return useQuery<ObservationNode[]>({
    queryKey: ['analytics', 'observations', traceId],
    queryFn: () => managedGet(`/analytics/observations/${traceId}`),
    enabled: !!traceId,
    staleTime: 120_000,
  })
}

// --- Agent Comparison ---

export function useAgentComparison(filters: AnalyticsFilters) {
  const params = buildFilterParams(filters)
  return useQuery<AgentMetrics[]>({
    queryKey: ['analytics', 'agent-comparison', params],
    queryFn: () => managedGet(`/analytics/agent-comparison${toQueryString(params)}`),
    staleTime: 60_000,
  })
}

export function useAgentTrend(
  filters: AnalyticsFilters,
  agentIds: string[],
  metric: string,
) {
  const params = {
    ...buildFilterParams(filters),
    agent_ids: agentIds.join(','),
    metric,
  }
  return useQuery<AgentTrendPoint[]>({
    queryKey: ['analytics', 'agent-trend', params],
    queryFn: () => managedGet(`/analytics/agent-trend${toQueryString(params)}`),
    enabled: agentIds.length > 0,
    staleTime: 60_000,
  })
}

// --- Agents for filter dropdowns ---

export function useAgentsForFilters() {
  return useQuery<{ id: string; name: string; engine_kind: string }[]>({
    queryKey: ['analytics', 'agents-for-filters'],
    queryFn: async () => {
      const result: any = await managedGet('/agents?limit=100')
      return Array.isArray(result) ? result : (result.data ?? [])
    },
    staleTime: 120_000,
  })
}

// --- Health Check ---

export function useHealthCheck(filters: AnalyticsFilters, alertConfig?: AlertConfig) {
  const params: Record<string, string> = { range: filters.range }
  if (filters.engine) params.engine = filters.engine
  if (filters.model) params.model = filters.model
  if (filters.status) params.status = filters.status
  if (filters.agent_id) params.agent_id = filters.agent_id

  // Add alert config params
  if (alertConfig) {
    params.consecutive_failures_enabled = String(alertConfig.consecutive_failures.enabled)
    params.consecutive_failures_threshold = String(alertConfig.consecutive_failures.threshold)
    params.slow_agent_enabled = String(alertConfig.slow_agent.enabled)
    params.slow_agent_threshold_ms = String(alertConfig.slow_agent.threshold)
    params.token_spike_enabled = String(alertConfig.token_spike.enabled)
    params.token_spike_threshold_pct = String(alertConfig.token_spike.threshold)
  }

  return useQuery<HealthCheckResponse>({
    queryKey: ['analytics', 'health-check', params],
    queryFn: () => managedGet(`/analytics/health-check${toQueryString(params)}`),
    staleTime: 30_000,
    refetchInterval: 30_000,
  })
}

// --- Error Summary ---

export function useErrorSummary(filters: AnalyticsFilters) {
  const params = buildFilterParams(filters)
  return useQuery<ErrorSummary>({
    queryKey: ['analytics', 'error-summary', params],
    queryFn: () => managedGet(`/analytics/error-summary${toQueryString(params)}`),
    staleTime: 60_000,
  })
}

// --- Latency Stats ---

export function useLatencyStats(filters: AnalyticsFilters) {
  const params = buildFilterParams(filters)
  return useQuery<LatencyStats>({
    queryKey: ['analytics', 'latency-stats', params],
    queryFn: () => managedGet(`/analytics/latency-stats${toQueryString(params)}`),
    staleTime: 60_000,
  })
}

// --- Agent Ranking ---

export function useAgentRanking(filters: AnalyticsFilters) {
  const params = buildFilterParams(filters)
  return useQuery<AgentRankingItem[]>({
    queryKey: ['analytics', 'agent-ranking', params],
    queryFn: () => managedGet(`/analytics/agent-ranking${toQueryString(params)}`),
    staleTime: 60_000,
  })
}

// --- Time Heatmap ---

export function useTimeHeatmap(filters: AnalyticsFilters) {
  const params = buildFilterParams(filters)
  return useQuery<HeatmapCell[]>({
    queryKey: ['analytics', 'time-heatmap', params],
    queryFn: () => managedGet(`/analytics/time-heatmap${toQueryString(params)}`),
    staleTime: 60_000,
  })
}
