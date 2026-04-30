import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import {
  ENGINE_KINDS,
  RUNTIME_KINDS,
} from '../agent'
import {
  ACTIVE_EXECUTION_STATUSES,
  ACTIVE_RUN_STATUSES,
  EXECUTION_STATUSES,
  RUN_STATUSES,
  TERMINAL_EXECUTION_STATUSES,
  TERMINAL_RUN_STATUSES,
  TRIGGER_MEDIUMS,
  RUN_PURPOSES,
} from '../agent-run'
import { RELEASE_STATUSES } from '../agent-release'

const readTypeSource = (relativePath: string) =>
  readFileSync(new URL(relativePath, import.meta.url), 'utf8')

const expectTypeDerivedFromConstant = (
  source: string,
  typeName: string,
  constantName: string,
) => {
  expect(source).toContain(
    `export type ${typeName} = (typeof ${constantName})[number]`,
  )
  expect(source.indexOf(`export const ${constantName}`)).toBeLessThan(
    source.indexOf(`export type ${typeName}`),
  )
}

describe('architecture contract types', () => {
  it('exports engine kinds', () => {
    expect([...ENGINE_KINDS].sort()).toEqual([
      'claude_code',
      'codex',
      'langgraph_code',
      'langgraph_visual',
      'openclaw',
    ])
  })

  it('exports runtime kinds', () => {
    expect([...RUNTIME_KINDS].sort()).toEqual(['sandbox', 'server'])
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

  it('exports trigger mediums', () => {
    expect([...TRIGGER_MEDIUMS].sort()).toEqual([
      'api',
      'scheduler',
      'system',
      'ui',
    ])
  })

  it('exports run purposes', () => {
    expect([...RUN_PURPOSES].sort()).toEqual([
      'debug',
      'draft_test',
      'internal_builder',
      'production',
    ])
  })

  it('derives agent type unions from exported const tuples', () => {
    const source = readTypeSource('../agent.ts')

    expectTypeDerivedFromConstant(source, 'EngineKind', 'ENGINE_KINDS')
    expectTypeDerivedFromConstant(source, 'RuntimeKind', 'RUNTIME_KINDS')
  })

  it('derives run type unions from exported const tuples', () => {
    const source = readTypeSource('../agent-run.ts')

    expectTypeDerivedFromConstant(source, 'TriggerMedium', 'TRIGGER_MEDIUMS')
    expectTypeDerivedFromConstant(source, 'RunPurpose', 'RUN_PURPOSES')
    expectTypeDerivedFromConstant(source, 'AgentRunStatus', 'RUN_STATUSES')
    expectTypeDerivedFromConstant(
      source,
      'ExecutionStatus',
      'EXECUTION_STATUSES',
    )
  })
})
