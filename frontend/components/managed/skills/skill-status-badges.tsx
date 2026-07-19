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

import { Loader2, ShieldCheck } from 'lucide-react'

import { useTranslation } from '@/lib/i18n'
import type { SkillLifecycleStatus, SkillRecord, SkillVisibility } from '@/types/managed'

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
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded border px-2 py-0.5 text-xs font-medium ${tone}`}
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
    status && status in LIFECYCLE_TONE ? (status as SkillLifecycleStatus) : 'approved'
  const labelKey = `managed.skills.lifecycle.${
    value === 'pending_review' ? 'pendingReview' : value
  }` as const
  return <Pill tone={LIFECYCLE_TONE[value]}>{t(labelKey)}</Pill>
}

export function SkillVisibilityBadge({
  visibility,
}: {
  visibility: SkillVisibility | string | undefined
}) {
  const { t } = useTranslation()
  const value: SkillVisibility =
    visibility && visibility in VISIBILITY_TONE ? (visibility as SkillVisibility) : 'project'
  const labelKey = `managed.skills.visibility.${value}` as const
  return <Pill tone={VISIBILITY_TONE[value]}>{t(labelKey)}</Pill>
}

export function SkillSecurityBadge({ status }: { status: string | undefined }) {
  const { t } = useTranslation()
  const value = status && status in SECURITY_TONE ? status : 'not_scanned'
  // Convert snake_case to the i18n key shape used in the locales file
  const key = value === 'not_scanned' ? 'notScanned' : value === 'scanning' ? 'scanning' : value
  // Show a tooltip on ``scanning`` so users understand the constraint
  // — agents won't load the skill until the BG scan lands.
  const title = value === 'scanning' ? t('managed.skills.security.scanningHint') : undefined
  return (
    <Pill tone={SECURITY_TONE[value]} title={title}>
      {value === 'scanning' && <Loader2 className="h-3 w-3 animate-spin" />}
      {t(`managed.skills.security.${key}`)}
    </Pill>
  )
}

/**
 * Risk score pill.
 *
 * The score is a *risk* score: higher = more dangerous (0 = clean/SAFE,
 * ≥70 = HIGH/CRITICAL → blocked). Colour therefore runs the opposite way
 * from a "grade" — red for high risk, green for zero risk. Thresholds mirror
 * the backend write-admission policy in ``joysafeter_skill_security.py``.
 */
export function SkillRiskScoreBadge({ score }: { score: number }) {
  const { t } = useTranslation()
  const tone =
    score >= 70
      ? 'bg-rose-50 text-rose-700 border-rose-200'
      : score > 0
        ? 'bg-amber-50 text-amber-700 border-amber-200'
        : 'bg-emerald-50 text-emerald-700 border-emerald-200'
  return (
    <Pill tone={tone} title={t('managed.skills.riskScoreHint')}>
      <ShieldCheck className="h-3 w-3" />
      <span className="tabular-nums">{t('managed.skills.riskScore', { score })}</span>
    </Pill>
  )
}

/**
 * Convenience: render all three badges side-by-side.
 *
 * Useful in the list view and the detail header — anywhere the operator
 * wants a quick "is this skill usable / where is it shared / what's its
 * review state" snapshot.
 *
 * ``showVisibility`` lets callers suppress the visibility pill when a
 * dedicated visibility control (e.g. the detail-header dropdown) already
 * shows and edits the same value — avoids showing "组织内" twice.
 */
export function SkillStatusBadges({
  skill,
  showVisibility = true,
}: {
  skill: SkillRecord
  showVisibility?: boolean
}) {
  return (
    <div className="inline-flex flex-wrap items-center gap-1.5">
      <SkillLifecycleBadge status={skill.lifecycle_status} />
      {showVisibility && (
        <SkillVisibilityBadge visibility={skill.visibility} />
      )}
      <SkillSecurityBadge status={skill.security_scan?.status} />
    </div>
  )
}
