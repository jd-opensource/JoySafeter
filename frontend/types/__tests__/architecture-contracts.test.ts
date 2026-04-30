import { describe, expect, it } from 'vitest'

import {
  BUILDER_DEFINITION_KINDS,
  RUNTIME_KINDS,
} from '../agent'
import {
  ACTIVE_EXECUTION_STATUSES,
  ACTIVE_RUN_STATUSES,
  EXECUTION_STATUSES,
  RUN_STATUSES,
  TERMINAL_EXECUTION_STATUSES,
  TERMINAL_RUN_STATUSES,
  TRIGGER_SOURCES,
} from '../agent-run'
import { RELEASE_STATUSES } from '../agent-release'

describe('architecture contract types', () => {
  it('exports builder definition kinds', () => {
    expect([...BUILDER_DEFINITION_KINDS].sort()).toEqual([
      'claude_code',
      'code',
      'codex',
      'graph',
      'openclaw',
    ])
  })

  it('exports runtime kinds', () => {
    expect([...RUNTIME_KINDS].sort()).toEqual(['code', 'graph', 'sandbox'])
  })

  it('exports run statuses', () => {
    expect([...RUN_STATUSES].sort()).toEqual([
      'cancelled',
      'failed',
      'pending',
      'running',
      'succeeded',
    ])
  })

  it('exports active run statuses', () => {
    expect([...ACTIVE_RUN_STATUSES].sort()).toEqual(['pending', 'running'])
  })

  it('exports terminal run statuses', () => {
    expect([...TERMINAL_RUN_STATUSES].sort()).toEqual([
      'cancelled',
      'failed',
      'succeeded',
    ])
  })

  it('exports execution statuses', () => {
    expect([...EXECUTION_STATUSES].sort()).toEqual([
      'approval_wait',
      'cancelled',
      'dispatched',
      'failed',
      'pending',
      'running',
      'succeeded',
    ])
  })

  it('exports active execution statuses', () => {
    expect([...ACTIVE_EXECUTION_STATUSES].sort()).toEqual([
      'approval_wait',
      'dispatched',
      'pending',
      'running',
    ])
  })

  it('exports terminal execution statuses', () => {
    expect([...TERMINAL_EXECUTION_STATUSES].sort()).toEqual([
      'cancelled',
      'failed',
      'succeeded',
    ])
  })

  it('exports release statuses', () => {
    expect([...RELEASE_STATUSES].sort()).toEqual([
      'active',
      'failed',
      'ready',
      'retired',
      'superseded',
    ])
  })

  it('exports trigger sources', () => {
    expect([...TRIGGER_SOURCES].sort()).toEqual([
      'api',
      'chat',
      'copilot',
      'debug',
      'draft_copilot',
      'draft_test',
      'scheduler',
      'task',
    ])
  })
})
