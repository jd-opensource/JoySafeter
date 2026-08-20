import type { QuickstartCapabilityEvidence } from './quickstart-capabilities'
import type { QuickstartTrialStatus } from './quickstart-trial-status'

export type QuickstartCheckStatus = 'passed' | 'failed' | 'not_observed'

export type QuickstartObservableCheckId = 'response' | 'access' | 'tools' | 'audit'

export interface QuickstartObservableCheck {
  id: QuickstartObservableCheckId
  status: QuickstartCheckStatus
}

const FAILED_TRIAL_STATUSES: ReadonlySet<QuickstartTrialStatus> = new Set([
  'error',
  'access_rejected',
  'runtime_unavailable',
])

/**
 * Derives the acceptance checks that can be verified from observed runtime signals.
 *
 * These are intentionally limited to what the session actually produced — a response,
 * whether access was rejected, whether declared capabilities were exercised, and
 * whether an audit trail exists. Free-text blueprint checks stay a manual checklist;
 * this function never guesses whether an arbitrary human criterion was met.
 */
export function deriveQuickstartObservableChecks({
  trialStatus,
  evidence,
  hasDeclaredCapabilities,
}: {
  trialStatus: QuickstartTrialStatus
  evidence: QuickstartCapabilityEvidence
  hasDeclaredCapabilities: boolean
}): QuickstartObservableCheck[] {
  const responseStatus: QuickstartCheckStatus = evidence.responseReceived
    ? 'passed'
    : FAILED_TRIAL_STATUSES.has(trialStatus)
      ? 'failed'
      : 'not_observed'

  const accessStatus: QuickstartCheckStatus =
    trialStatus === 'access_rejected'
      ? 'failed'
      : evidence.responseReceived
        ? 'passed'
        : 'not_observed'

  const checks: QuickstartObservableCheck[] = [
    { id: 'response', status: responseStatus },
    { id: 'access', status: accessStatus },
  ]

  if (hasDeclaredCapabilities) {
    const toolsObserved = evidence.observedTools.length > 0 || evidence.observedMcpTools.length > 0
    checks.push({ id: 'tools', status: toolsObserved ? 'passed' : 'not_observed' })
  }

  checks.push({
    id: 'audit',
    status: evidence.auditEventsAvailable ? 'passed' : 'not_observed',
  })

  return checks
}
