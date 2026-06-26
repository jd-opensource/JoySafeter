/**
 * Status / visibility / security badges for skill records.
 *
 * Reads ``visibility`` / ``lifecycle_status`` / ``security_scan.status`` from
 * a :type:`SkillRecord` and renders coloured pills the operator can scan at a
 * glance in the list and detail views.
 *
 * Three independent dimensions, three independent badges — composed via
 * ``SkillStatusBadges`` for callers that want all three.
 */

'use client'

import { useTranslation } from '@/lib/i18n'
import type {
  SkillLifecycleStatus,
  SkillRecord,
  SkillVisibility,
} from '@/types/managed'

// Tailwind-friendly tone tuples — each maps to (bg, text, border).
// Kept inline so a single review covers every status's colour at once.
const LIFECYCLE_TONE: Record<SkillLifecycleStatus, string> = {
  draft: 'bg-slate-100 text-slate-700 border-slate-200',
  pending_review: 'bg-amber-50 text-amber-700 border-amber-200',
  approved: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  rejected: 'bg-rose-50 text-rose-700 border-rose-200',
  archived: 'bg-zinc-100 text-zinc-600 border-zinc-200',
}

const VISIBILITY_TONE: Record<SkillVisibility, string> = {
  private: 'bg-slate-100 text-slate-700 border-slate-200',
  project: 'bg-sky-50 text-sky-700 border-sky-200',
  organization: 'bg-violet-50 text-violet-700 border-violet-200',
  public: 'bg-blue-50 text-blue-700 border-blue-200',
}

// Security status maps to roughly the same palette as lifecycle so the
// two columns "feel related" without needing a legend.
const SECURITY_TONE: Record<string, string> = {
  passed: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  warning: 'bg-amber-50 text-amber-700 border-amber-200',
  blocked: 'bg-rose-50 text-rose-700 border-rose-200',
  failed: 'bg-rose-50 text-rose-700 border-rose-200',
  not_scanned: 'bg-slate-100 text-slate-600 border-slate-200',
  scanning: 'bg-indigo-50 text-indigo-700 border-indigo-200',
}

function Pill({
  tone,
  children,
  title,
}: {
  tone: string
  children: React.ReactNode
  title?: string
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-medium ${tone}`}
      title={title}
    >
      {children}
    </span>
  )
}

export function SkillLifecycleBadge({
  status,
}: {
  status: SkillLifecycleStatus | string | undefined
}) {
  const { t } = useTranslation()
  // Default to 'approved' so legacy skills written before P1 (no
  // lifecycle_status field on the response) render normally rather
  // than as an empty pill.
  const value: SkillLifecycleStatus =
    status && status in LIFECYCLE_TONE
      ? (status as SkillLifecycleStatus)
      : 'approved'
  const labelKey = `managed.skills.lifecycle.${
    value === 'pending_review' ? 'pendingReview' : value
  }` as const
  return <Pill tone={LIFECYCLE_TONE[value]}>{t(labelKey)}</Pill>
}

export function SkillVisibilityBadge({
  visibility,
  isPublic,
}: {
  visibility: SkillVisibility | string | undefined
  isPublic?: boolean
}) {
  const { t } = useTranslation()
  // Read visibility first; fall back to is_public for legacy rows.
  let value: SkillVisibility = 'private'
  if (visibility && visibility in VISIBILITY_TONE) {
    value = visibility as SkillVisibility
  } else if (isPublic) {
    value = 'public'
  }
  const labelKey = `managed.skills.visibility.${value}` as const
  return <Pill tone={VISIBILITY_TONE[value]}>{t(labelKey)}</Pill>
}

export function SkillSecurityBadge({
  status,
}: {
  status: string | undefined
}) {
  const { t } = useTranslation()
  const value = status && status in SECURITY_TONE ? status : 'not_scanned'
  // Convert snake_case to the i18n key shape used in the locales file
  const key =
    value === 'not_scanned'
      ? 'notScanned'
      : value === 'scanning'
        ? 'scanning'
        : value
  // Show a tooltip on ``scanning`` so users understand the constraint
  // — agents won't load the skill until the BG scan lands.
  const title = value === 'scanning' ? t('managed.skills.security.scanningHint') : undefined
  return (
    <Pill tone={SECURITY_TONE[value]} title={title}>
      {t(`managed.skills.security.${key}`)}
    </Pill>
  )
}

/**
 * Convenience: render all three badges side-by-side.
 *
 * Useful in the list view and the detail header — anywhere the operator
 * wants a quick "is this skill usable / where is it shared / what's its
 * review state" snapshot.
 */
export function SkillStatusBadges({ skill }: { skill: SkillRecord }) {
  return (
    <div className="inline-flex flex-wrap items-center gap-1.5">
      <SkillLifecycleBadge status={skill.lifecycle_status} />
      <SkillVisibilityBadge
        visibility={skill.visibility}
        isPublic={skill.is_public}
      />
      <SkillSecurityBadge status={skill.security_scan?.status} />
    </div>
  )
}
