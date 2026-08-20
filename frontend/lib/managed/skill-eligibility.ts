/**
 * Single source of truth for presenting unpublished-skill availability.
 *
 * The backend contract is intentionally machine-only: ``reason`` (what's
 * wrong) and ``next_action`` (what to do). ALL human-facing, localized copy
 * lives here + in the i18n locales — never baked into the backend. Both the
 * skill detail banner and the create-agent skill picker consume this module
 * so the same state renders identically everywhere.
 *
 * - ``reason``      → a localized title + a short label (compact pills)
 * - ``next_action`` → a localized, LOCATION-NEUTRAL next-step hint
 */

// reason machine code → i18n slug (camelCase leaf under managed.skills.eligibility.*)
const REASON_SLUG: Record<string, string> = {
  no_published_version: 'noPublishedVersion',
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
  /** Location-neutral next-step hint (safe to show on any surface). */
  hintKey: string
}

export function eligibilityActionView(
  nextAction: string | null | undefined,
): EligibilityActionView {
  const code = nextAction || 'review_skill'
  return {
    hintKey: `managed.skills.eligibility.action.${code}`,
  }
}
