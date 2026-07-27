/**
 * Presenter for skill security-scan severity. The scanner emits a fixed
 * SCREAMING_CASE enum (CRITICAL/HIGH/MEDIUM/LOW/INFO, plus an UNKNOWN fallback);
 * this maps it to a localized i18n key so no raw machine code reaches users.
 * Free-form scanner text (category, recommendation, findings) is intentionally
 * left as-is — only the closed severity enum is localized here.
 */

// severity enum (case-insensitive) → i18n leaf under managed.skills.severityLabel.*
const SEVERITY_SLUG: Record<string, string> = {
  critical: 'critical',
  high: 'high',
  medium: 'medium',
  low: 'low',
  info: 'info',
  informational: 'info',
  unknown: 'unknown',
}

/** Severity → i18n key for its localized label. Unmapped values fall back to "unknown". */
export function severityLabelKey(severity: string | null | undefined): string {
  const slug = (severity && SEVERITY_SLUG[severity.toLowerCase()]) || 'unknown'
  return `managed.skills.severityLabel.${slug}`
}
