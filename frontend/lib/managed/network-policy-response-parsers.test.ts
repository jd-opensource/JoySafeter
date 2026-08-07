import { describe, expect, it } from 'vitest'

import {
  parseNetworkPolicyListResponse,
  parseNetworkPolicyStatusResponse,
} from './network-policy-response-parsers'

const SANDBOX_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f030'
const SESSION_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f031'
const TASK_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f032'

const rawStatus = () => ({
  sandbox_id: `sbx_${SANDBOX_UUID}`,
  session_id: `sess_${SESSION_UUID}`,
  task_id: `task_${TASK_UUID}`,
  sandbox_status: 'running',
  networking_status: 'ready',
  networking_policy_version: 3,
  sandbox_updated_at: '2026-08-06T00:00:00Z',
})

describe('network policy response parsers', () => {
  it('parses sandbox, session, and task IDs at the API boundary', () => {
    const status = parseNetworkPolicyStatusResponse(rawStatus())
    expect(status.sandbox_id).toBe(`sbx_${SANDBOX_UUID}`)
    expect(status.session_id).toBe(`sess_${SESSION_UUID}`)
    expect(status.task_id).toBe(`task_${TASK_UUID}`)

    const list = parseNetworkPolicyListResponse({
      data: [rawStatus()],
      total: 1,
      page: 1,
      page_size: 10,
    })
    expect(list.data[0].sandbox_id).toBe(`sbx_${SANDBOX_UUID}`)
  })

  it('preserves nullable related IDs', () => {
    const status = parseNetworkPolicyStatusResponse({
      ...rawStatus(),
      session_id: null,
      task_id: undefined,
    })
    expect(status.session_id).toBeNull()
    expect(status.task_id).toBeUndefined()
  })

  it('rejects bare and cross-entity sandbox IDs', () => {
    expect(() =>
      parseNetworkPolicyStatusResponse({ ...rawStatus(), sandbox_id: SANDBOX_UUID }),
    ).toThrow()
    expect(() =>
      parseNetworkPolicyStatusResponse({
        ...rawStatus(),
        sandbox_id: `task_${SANDBOX_UUID}`,
      }),
    ).toThrow()
  })
})
