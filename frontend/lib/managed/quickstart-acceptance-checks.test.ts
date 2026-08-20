import { describe, expect, it } from 'vitest'

import { deriveQuickstartObservableChecks } from './quickstart-acceptance-checks'
import type { QuickstartCapabilityEvidence } from './quickstart-capabilities'

function evidence(
  overrides: Partial<QuickstartCapabilityEvidence> = {},
): QuickstartCapabilityEvidence {
  return {
    responseReceived: false,
    environmentAttached: false,
    externalToolsAuthorized: false,
    configuredSkills: [],
    observedTools: [],
    observedMcpTools: [],
    auditEventsAvailable: false,
    ...overrides,
  }
}

describe('deriveQuickstartObservableChecks', () => {
  it('passes response, access, and audit and marks declared tools observed', () => {
    const checks = deriveQuickstartObservableChecks({
      trialStatus: 'response_received',
      evidence: evidence({
        responseReceived: true,
        observedTools: ['Read'],
        auditEventsAvailable: true,
      }),
      hasDeclaredCapabilities: true,
    })
    expect(checks).toEqual([
      { id: 'response', status: 'passed' },
      { id: 'access', status: 'passed' },
      { id: 'tools', status: 'passed' },
      { id: 'audit', status: 'passed' },
    ])
  })

  it('fails response and access when launch access was rejected', () => {
    const checks = deriveQuickstartObservableChecks({
      trialStatus: 'access_rejected',
      evidence: evidence({ auditEventsAvailable: true }),
      hasDeclaredCapabilities: false,
    })
    expect(checks).toEqual([
      { id: 'response', status: 'failed' },
      { id: 'access', status: 'failed' },
      { id: 'audit', status: 'passed' },
    ])
  })

  it('marks everything not observed before a trial has produced signals', () => {
    const checks = deriveQuickstartObservableChecks({
      trialStatus: 'testing',
      evidence: evidence(),
      hasDeclaredCapabilities: true,
    })
    expect(checks).toEqual([
      { id: 'response', status: 'not_observed' },
      { id: 'access', status: 'not_observed' },
      { id: 'tools', status: 'not_observed' },
      { id: 'audit', status: 'not_observed' },
    ])
  })

  it('reports declared tools that were never exercised as not observed after a response', () => {
    const checks = deriveQuickstartObservableChecks({
      trialStatus: 'response_received',
      evidence: evidence({ responseReceived: true, auditEventsAvailable: true }),
      hasDeclaredCapabilities: true,
    })
    expect(checks.find((check) => check.id === 'tools')).toEqual({
      id: 'tools',
      status: 'not_observed',
    })
  })

  it('omits the tools check when the agent declared no tools, skills, or MCP servers', () => {
    const checks = deriveQuickstartObservableChecks({
      trialStatus: 'response_received',
      evidence: evidence({ responseReceived: true }),
      hasDeclaredCapabilities: false,
    })
    expect(checks.some((check) => check.id === 'tools')).toBe(false)
  })
})
