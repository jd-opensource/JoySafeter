import { describe, expect, it } from 'vitest'

import {
  QUICKSTART_RUNTIME_PENDING_TIMEOUT_MS,
  deriveQuickstartTrialStatus,
} from './quickstart-trial-status'

const NOW = Date.parse('2026-08-07T03:00:00.000Z')

function event(type: string) {
  return { type }
}

function task(status: string, ageMs: number) {
  return {
    id: 'task_019fda0d-8c1c-7df3-9b79-f7b25a441960',
    status,
    created_at: new Date(NOW - ageMs).toISOString(),
    started_at: null,
    completed_at: null,
    error: null,
  }
}

describe('deriveQuickstartTrialStatus', () => {
  it('stays idle before a user message exists', () => {
    expect(
      deriveQuickstartTrialStatus({
        isSessionActive: true,
        events: [],
        task: null,
        nowMs: NOW,
      }),
    ).toBe('idle')
  })

  it('reports normal testing while work is running', () => {
    expect(
      deriveQuickstartTrialStatus({
        isSessionActive: true,
        events: [event('user.message'), event('session.status_running')],
        task: task('running', QUICKSTART_RUNTIME_PENDING_TIMEOUT_MS * 2),
        nowMs: NOW,
      }),
    ).toBe('testing')
  })

  it('reports success after an agent reply returns idle', () => {
    expect(
      deriveQuickstartTrialStatus({
        isSessionActive: true,
        events: [event('user.message'), event('agent.message'), event('session.status_idle')],
        task: task('completed', 5_000),
        nowMs: NOW,
      }),
    ).toBe('success')
  })

  it('gives explicit session termination precedence', () => {
    expect(
      deriveQuickstartTrialStatus({
        isSessionActive: true,
        events: [event('user.message'), event('session.status_terminated')],
        task: task('pending', QUICKSTART_RUNTIME_PENDING_TIMEOUT_MS * 2),
        nowMs: NOW,
      }),
    ).toBe('error')
  })

  it.each(['failed', 'aborted', 'timeout', 'cancelled'])(
    'reports terminal task status %s as an error',
    (status) => {
      expect(
        deriveQuickstartTrialStatus({
          isSessionActive: true,
          events: [event('user.message')],
          task: task(status, 5_000),
          nowMs: NOW,
        }),
      ).toBe('error')
    },
  )

  it('keeps a newly pending task in testing', () => {
    expect(
      deriveQuickstartTrialStatus({
        isSessionActive: true,
        events: [event('user.message')],
        task: task('pending', QUICKSTART_RUNTIME_PENDING_TIMEOUT_MS - 1),
        nowMs: NOW,
      }),
    ).toBe('testing')
  })

  it.each(['pending', 'scheduling'])(
    'reports an old %s task as runtime unavailable',
    (status) => {
      expect(
        deriveQuickstartTrialStatus({
          isSessionActive: true,
          events: [event('user.message')],
          task: task(status, QUICKSTART_RUNTIME_PENDING_TIMEOUT_MS),
          nowMs: NOW,
        }),
      ).toBe('runtime_unavailable')
    },
  )
})
