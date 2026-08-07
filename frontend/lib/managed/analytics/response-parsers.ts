import {
  parseAgentId,
  parseSessionId,
  parseTaskId,
  type AgentId,
  type SessionId,
} from '@/types/entity-id'

import type {
  AgentMetrics,
  AgentRankingItem,
  AgentTrendPoint,
  AlertItem,
  CallRecord,
  CallsListResponse,
  HealthCheckResponse,
} from './types'

type RawCallRecord = Omit<CallRecord, 'id' | 'trace_id' | 'session_id' | 'agent_id'> & {
  id: string
  trace_id: string
  session_id: string | null
  agent_id: string | null
}

type RawCallsListResponse = Omit<CallsListResponse, 'data'> & { data: RawCallRecord[] }
type RawAgentMetrics = Omit<AgentMetrics, 'agent_id'> & { agent_id: string }
type RawAgentTrendPoint = Omit<AgentTrendPoint, 'agent_id'> & { agent_id: string }
type RawAlertItem = Omit<AlertItem, 'agent_id'> & { agent_id: string | null }
type RawHealthCheckResponse = Omit<HealthCheckResponse, 'alerts'> & { alerts: RawAlertItem[] }
type RawAgentRankingItem = Omit<AgentRankingItem, 'agent_id'> & { agent_id: string }

function parseNullableId<T>(value: string | null, parse: (raw: string) => T): T | null {
  return value === null ? null : parse(value)
}

export function parseCallsListResponse(response: RawCallsListResponse): CallsListResponse {
  return {
    ...response,
    data: response.data.map((record) => ({
      ...record,
      id: parseTaskId(record.id),
      trace_id: parseTaskId(record.trace_id),
      session_id: parseNullableId<SessionId>(record.session_id, parseSessionId),
      agent_id: parseNullableId<AgentId>(record.agent_id, parseAgentId),
    })),
  }
}

export function parseAgentMetricsResponse(response: RawAgentMetrics[]): AgentMetrics[] {
  return response.map((item) => ({ ...item, agent_id: parseAgentId(item.agent_id) }))
}

export function parseAgentTrendResponse(response: RawAgentTrendPoint[]): AgentTrendPoint[] {
  return response.map((item) => ({ ...item, agent_id: parseAgentId(item.agent_id) }))
}

export function parseHealthCheckResponse(response: RawHealthCheckResponse): HealthCheckResponse {
  return {
    ...response,
    alerts: response.alerts.map((alert) => ({
      ...alert,
      agent_id: parseNullableId<AgentId>(alert.agent_id, parseAgentId),
    })),
  }
}

export function parseAgentRankingResponse(response: RawAgentRankingItem[]): AgentRankingItem[] {
  return response.map((item) => ({ ...item, agent_id: parseAgentId(item.agent_id) }))
}
