/**
 * Analytics data types for JoySafeter monitoring dashboard.
 * These types define the API response shapes consumed by chart components.
 */

// --- KPI Summary ---

export interface AnalyticsDelta {
  total_calls: number | null
  success_rate: number | null
  avg_duration_ms: number | null
  avg_ttft_ms: number | null
  total_tokens: number | null
  total_cost: number | null
  error_count: number | null
  active_sessions: number | null
}

export interface AnalyticsSummary {
  total_calls: number
  success_rate: number
  avg_duration_ms: number
  avg_ttft_ms: number
  total_tokens: number
  total_cost: number
  error_count: number
  active_sessions: number
  avg_agent_steps: number
  delta: AnalyticsDelta
}

// --- Time Series ---

export type TimeRange = '24h' | '7d' | '30d' | '90d' | 'all'

export type MetricType = 'calls' | 'tokens' | 'latency'

export interface CallsTimePoint {
  timestamp: string
  total_calls: number
  error_calls: number
  success_calls: number
}

export interface TokensTimePoint {
  timestamp: string
  input_tokens: number
  output_tokens: number
}

export interface LatencyTimePoint {
  timestamp: string
  avg_duration_ms: number
  avg_ttft_ms: number
}

// --- Engine Share ---

export interface EngineShareItem {
  engine: string
  count: number
  percentage: number
}

// --- Call Records ---

export type CallStatus = 'running' | 'completed' | 'error' | 'timeout' | 'cancelled'

export interface CallRecord {
  id: string
  trace_id: string
  session_id: string
  agent_id: string
  agent_name: string
  engine_kind: string
  model: string
  status: CallStatus
  input_tokens: number
  output_tokens: number
  total_tokens: number
  ttft_ms: number | null
  duration_ms: number
  cost: number
  agent_steps: number
  error: string | null
  started_at: string
  completed_at: string | null
  retry_count: number
  queue_wait_ms: number
}

export interface CallsListResponse {
  data: CallRecord[]
  has_more: boolean
  total: number
}

// --- Observations (Waterfall) ---

export type ObservationType =
  | 'SPAN'
  | 'EVENT'
  | 'GENERATION'
  | 'AGENT'
  | 'TOOL'
  | 'CHAIN'
  | 'RETRIEVER'
  | 'EMBEDDING'
  | 'EVALUATOR'
  | 'GUARDRAIL'

export type ObservationLevel = 'DEBUG' | 'DEFAULT' | 'WARNING' | 'ERROR'

export interface ObservationNode {
  id: string
  parent_id: string | null
  type: ObservationType
  level: ObservationLevel
  name: string
  model: string | null
  start_time: string
  end_time: string | null
  completion_start_time: string | null
  duration_ms: number
  input_tokens: number
  output_tokens: number
  cost: number
  tool_calls: unknown[] | null
  children: ObservationNode[]
}

// --- Agent Comparison ---

export interface AgentMetrics {
  agent_id: string
  agent_name: string
  engine_kind: string
  total_sessions: number
  total_tasks: number
  success_rate: number
  avg_duration_ms: number
  avg_ttft_ms: number
  avg_cost: number
  total_tokens: number
  avg_agent_steps: number
}

// --- Filter State ---

export interface AnalyticsFilters {
  range: TimeRange
  engine: string | null
  model: string | null
  status: CallStatus | null
  agent_id: string | null
}

// --- Health Check ---

export type HealthStatus = 'healthy' | 'warning' | 'critical'

export type AlertSeverity = 'error' | 'warning' | 'info'

export interface AlertItem {
  type: string
  severity: AlertSeverity
  agent_name: string | null
  agent_id: string | null
  params: Record<string, number>
}

export interface TokenSummary {
  total: number
  input: number
  output: number
  cache_read: number
  cache_hit_rate: number
}

export interface QueueWaitInfo {
  avg_sec: number
  max_sec: number
}

export interface HealthCheckResponse {
  status: HealthStatus
  success_rate: number
  running_tasks: number
  last_error_at: string | null
  alerts: AlertItem[]
  token_summary: TokenSummary
  suggestions: SuggestionItem[]
  queue_wait: QueueWaitInfo
}

// --- Suggestions ---

export interface SuggestionItem {
  type: string
  params: Record<string, number>
}

// --- Error Summary ---

export interface ErrorSummary {
  total_errors: number
  status_breakdown: { status: string; count: number }[]
  top_errors: { message: string; count: number }[]
}

// --- Latency Stats ---

export interface DurationBucket {
  label: string
  count: number
  pct: number
  color: 'emerald' | 'amber' | 'red'
}

export interface LatencyStats {
  total_calls: number
  buckets: DurationBucket[]
}

// --- Agent Ranking ---

export interface AgentRankingItem {
  agent_id: string
  agent_name: string
  engine_kind: string
  total_tasks: number
  success_rate: number
  failed_count: number
  avg_duration_ms: number
  total_tokens: number
  last_task_at: string | null
  activity_status: 'active' | 'idle' | 'unused'
}

// --- Time Heatmap ---

export interface HeatmapCell {
  day: number // 0=Sunday, 1=Monday...6=Saturday
  hour: number // 0-23
  count: number
  error_count: number
}

// --- Alert Configuration ---

export interface AlertRuleConfig {
  enabled: boolean
  threshold: number
}

export interface AlertConfig {
  consecutive_failures: AlertRuleConfig
  slow_agent: AlertRuleConfig
  token_spike: AlertRuleConfig
}
