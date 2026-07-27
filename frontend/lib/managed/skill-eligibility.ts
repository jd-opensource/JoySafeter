/**
 * Single source of truth for presenting skill runtime-eligibility to users.
 *
 * The backend contract is intentionally machine-only: ``reason`` (what's
 * wrong) and ``next_action`` (what to do). ALL human-facing, localized copy
 * lives here + in the i18n locales — never baked into the backend. Both the
 * skill detail banner and the create-agent skill picker consume this module
 * so the same state renders identically everywhere.
 *
 * - ``reason``      → a localized title + a short label (compact pills)
 * - ``next_action`` → a localized, LOCATION-NEUTRAL next-step hint + a "kind"
 *   the surface uses to pick its own affordance (existing toolbar buttons on
 *   the detail page, a deep link in the agent picker, etc.)
 */

// Which affordance a surface should offer for a given next_action. The copy is
// shared; the control is chosen per-surface (the detail page already has the
// real buttons in its toolbar; the agent picker can only deep-link out).
export type EligibilityActionKind = 'lifecycle' | 'rescan' | 'wait' | 'none'

// reason machine code → i18n slug (camelCase leaf under managed.skills.eligibility.*)
const REASON_SLUG: Record<string, string> = {
  skill_not_approved: 'skillNotApproved',
  security_not_scanned: 'securityNotScanned',
  security_scanning: 'securityScanning',
  security_failed: 'securityFailed',
  security_blocked: 'securityBlocked',
  no_security_scan_hash: 'noSecurityScanHash',
  content_changed_after_scan: 'contentChangedAfterScan',
  // Frontend-only codes invented by the agent skill picker (a skill with no
  // published version, or a generic "not usable" fallback). Folded in here so
  // the picker maps them through the same table instead of showing raw codes.
  no_published_version: 'noPublishedVersion',
  runtime_not_ready: 'runtimeNotReady',
}

// next_action machine code → affordance kind
const ACTION_KIND: Record<string, EligibilityActionKind> = {
  submit_or_approve: 'lifecycle',
  run_security_scan: 'rescan',
  fix_and_rescan: 'rescan',
  wait_for_scan: 'wait',
  review_skill: 'none',
  none: 'none',
}

export interface EligibilityReasonView {
  /** Full title, e.g. banner heading. */
  titleKey: string
  /** Short label for compact pills (agent picker). */
  shortKey: string
}

export function eligibilityReasonView(reason: string | null | undefined): EligibilityReasonView {
  const slug = (reason && REASON_SLUG[reason]) || 'unknown'
  return {
    titleKey: `managed.skills.eligibility.title.${slug}`,
    shortKey: `managed.skills.eligibility.short.${slug}`,
  }
}

export interface EligibilityActionView {
  kind: EligibilityActionKind
  /** Location-neutral next-step hint (safe to show on any surface). */
  hintKey: string
}

export function eligibilityActionView(nextAction: string | null | undefined): EligibilityActionView {
  const code = nextAction || 'review_skill'
  return {
    kind: ACTION_KIND[code] ?? 'none',
    hintKey: `managed.skills.eligibility.action.${code}`,
  }
}
