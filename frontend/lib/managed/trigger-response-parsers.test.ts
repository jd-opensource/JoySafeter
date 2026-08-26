import { describe, expect, it } from 'vitest'

import {
  parseAgentTriggerResponse,
  parseTriggerFireResultResponse,
  parseTriggerRunResponse,
} from './trigger-response-parsers'

const UUID = '018f47a5-7b21-7c34-9d02-123456789abc'

function rawTrigger() {
  return {
    id: `trig_${UUID}`,
    name: 'Trigger',
    description: null,
    type: 'webhook' as const,
    agent_id: `agent_${UUID}`,
    prompt_template: 'Run',
    environment_id: `env_${UUID}`,
    enabled: true,
    session_mode: 'fresh' as const,
    pinned_session_id: null,
    reusable_session_id: `sess_${UUID}`,
    session_key: null,
    filter: {},
    timeout_sec: 300,
    max_retries: 0,
    project_id: null,
    webhook_url: null,
    last_attempt_at: null,
    last_success_at: null,
    last_error: null,
    consecutive_failures: 0,
    last_task_id: `task_${UUID}`,
    last_session_id: `sess_${UUID}`,
    last_payload: {},
    created_at: '2026-08-06T00:00:00Z',
    updated_at: '2026-08-06T00:00:00Z',
  }
}

describe('trigger response parsers', () => {
  it('brands canonical trigger graph ids at the API boundary', () => {
    const trigger = parseAgentTriggerResponse(rawTrigger())
    const run = parseTriggerRunResponse({
      id: `task_${UUID}`,
      trigger_id: `trig_${UUID}`,
      status: 'completed',
      retry_count: 0,
      max_retries: 0,
      chat_session_id: `sess_${UUID}`,
      error: null,
      created_at: '2026-08-06T00:00:00Z',
      started_at: null,
      completed_at: null,
    })
    const fire = parseTriggerFireResultResponse({
      status: 'fired',
      task_id: `task_${UUID}`,
      session_id: `sess_${UUID}`,
    })

    expect(trigger.id).toBe(`trig_${UUID}`)
    expect(trigger.agent_id).toBe(`agent_${UUID}`)
    expect(trigger.environment_id).toBe(`env_${UUID}`)
    expect(trigger.last_task_id).toBe(`task_${UUID}`)
    expect(run.trigger_id).toBe(`trig_${UUID}`)
    expect(run.id).toBe(`task_${UUID}`)
    expect(fire.session_id).toBe(`sess_${UUID}`)
  })

  it('rejects bare and cross-entity trigger ids', () => {
    expect(() => parseAgentTriggerResponse({ ...rawTrigger(), id: UUID })).toThrow()
    expect(() =>
      parseAgentTriggerResponse({ ...rawTrigger(), environment_id: `agent_${UUID}` }),
    ).toThrow()
    expect(() =>
      parseTriggerRunResponse({
        id: `task_${UUID}`,
        trigger_id: `agent_${UUID}`,
        status: 'completed',
        retry_count: 0,
        max_retries: 0,
        chat_session_id: null,
        error: null,
        created_at: '2026-08-06T00:00:00Z',
        started_at: null,
        completed_at: null,
      }),
    ).toThrow()
  })
})
