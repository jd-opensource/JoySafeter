import { describe, expect, it } from 'vitest'

import {
  parseAgentMetricsResponse,
  parseAgentRankingResponse,
  parseCallsListResponse,
  parseHealthCheckResponse,
} from './response-parsers'

const UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f004'

describe('analytics response ID parsers', () => {
  it('brands canonical call record IDs at the API boundary', () => {
    const response = parseCallsListResponse({
      data: [
        {
          id: `task_${UUID}`,
          trace_id: `task_${UUID}`,
          session_id: `sess_${UUID}`,
          agent_id: `agent_${UUID}`,
          agent_name: 'Agent',
          engine_kind: 'claude_code',
          model: 'model',
          status: 'completed',
          input_tokens: 1,
          output_tokens: 2,
          total_tokens: 3,
          ttft_ms: null,
          duration_ms: 4,
          cost: 0,
          agent_steps: 1,
          error: null,
          started_at: '2026-08-06T00:00:00Z',
          completed_at: null,
          retry_count: 0,
          queue_wait_ms: 0,
        },
      ],
      has_more: false,
      total: 1,
    })

    expect(response.data[0]).toMatchObject({
      id: `task_${UUID}`,
      trace_id: `task_${UUID}`,
      session_id: `sess_${UUID}`,
      agent_id: `agent_${UUID}`,
    })
  })

  it('rejects bare and cross-entity IDs from analytics responses', () => {
    expect(() =>
      parseAgentMetricsResponse([
        {
          agent_id: UUID,
          agent_name: 'Agent',
          engine_kind: 'claude_code',
          total_sessions: 0,
          total_tasks: 0,
          success_rate: 0,
          avg_duration_ms: 0,
          avg_ttft_ms: 0,
          avg_cost: 0,
          total_tokens: 0,
          avg_agent_steps: 0,
        },
      ]),
    ).toThrow()

    expect(() =>
      parseAgentRankingResponse([
        {
          agent_id: `sess_${UUID}`,
          agent_name: 'Agent',
          engine_kind: 'claude_code',
          total_tasks: 0,
          success_rate: 0,
          failed_count: 0,
          avg_duration_ms: 0,
          total_tokens: 0,
          last_task_at: null,
          activity_status: 'unused',
        },
      ]),
    ).toThrow()
  })

  it('preserves nullable alert identity', () => {
    const response = parseHealthCheckResponse({
      status: 'healthy',
      success_rate: 1,
      running_tasks: 0,
      last_error_at: null,
      alerts: [
        {
          type: 'token_spike',
          severity: 'info',
          agent_name: null,
          agent_id: null,
          params: {},
        },
      ],
      token_summary: { total: 0, input: 0, output: 0, cache_read: 0, cache_hit_rate: 0 },
      suggestions: [],
      queue_wait: { avg_sec: 0, max_sec: 0 },
    })

    expect(response.alerts[0].agent_id).toBeNull()
  })
})
