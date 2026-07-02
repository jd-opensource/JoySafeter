'use client'

/**
 * GitHub "Files changed" style renderer for a Skill version diff.
 *
 * Renders a summary bar plus one collapsible block per changed file. Each file
 * shows its diff as GitHub-style hunks (``@@`` headers with collapsed context),
 * in either Unified (one column) or Split (old | new side-by-side) mode. The
 * mode toggle is owned by the parent so it can sit in the page header.
 */
import { useState } from 'react'
import { ChevronDown, ChevronRight, FileText, GitCompare } from 'lucide-react'

import { useTranslation } from '@/lib/i18n'
import type {
  DiffHunk,
  DiffRow,
  SkillFileDiffEntry,
  SkillVersionDiff,
} from '@/lib/managed/skill-version-diff'

export type DiffViewMode = 'unified' | 'split'

function StatusBadge({ status }: { status: SkillFileDiffEntry['status'] }) {
  const { t } = useTranslation()
  if (status === 'unchanged') return null
  const map = {
    added: {
      label: t('managed.skills.versionDiffFileAdded'),
      cls: 'bg-green-500/10 text-green-700 dark:text-green-300',
    },
    removed: {
      label: t('managed.skills.versionDiffFileRemoved'),
      cls: 'bg-red-500/10 text-red-700 dark:text-red-300',
    },
    modified: {
      label: t('managed.skills.versionDiffFileModified'),
      cls: 'bg-amber-500/10 text-amber-700 dark:text-amber-300',
    },
  } as const
  const { label, cls } = map[status]
  return (
    <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${cls}`}>{label}</span>
  )
}

const LineNo = ({ n }: { n: number | null }) => (
  <span className="border-border/50 w-11 shrink-0 select-none border-r px-2 text-right text-muted-foreground/50">
    {n ?? ''}
  </span>
)

const rowBg = (type: DiffRow['type']) =>
  type === 'add' ? 'bg-green-500/10' : type === 'remove' ? 'bg-red-500/10' : ''
const rowText = (type: DiffRow['type']) =>
  type === 'add'
    ? 'text-green-700 dark:text-green-300'
    : type === 'remove'
      ? 'text-red-700 dark:text-red-300'
      : 'text-foreground/80'

function HunkHeader({ header }: { header: string }) {
  return (
    <div className="bg-sky-500/5 px-3 py-1 font-mono text-[11px] text-sky-700/70 dark:text-sky-300/60">
      {header}
    </div>
  )
}

// ── Unified: single column, +/- gutter ──
function UnifiedHunk({ hunk }: { hunk: DiffHunk }) {
  return (
    <>
      <HunkHeader header={hunk.header} />
      {hunk.rows.map((r, i) => {
        const sign = r.type === 'add' ? '+' : r.type === 'remove' ? '-' : ' '
        return (
          <div key={i} className={`flex ${rowBg(r.type)}`}>
            <LineNo n={r.oldNo} />
            <LineNo n={r.newNo} />
            <span className={`w-4 shrink-0 select-none text-center ${rowText(r.type)}`}>
              {sign}
            </span>
            <span className={`whitespace-pre-wrap break-all px-1 ${rowText(r.type)}`}>
              {r.value || ' '}
            </span>
          </div>
        )
      })}
    </>
  )
}

// ── Split: old (left) | new (right). Pair remove/add rows onto the same line. ──
type SplitRow = { old: DiffRow | null; new: DiffRow | null }

function toSplitRows(rows: DiffRow[]): SplitRow[] {
  const out: SplitRow[] = []
  let i = 0
  while (i < rows.length) {
    const r = rows[i]
    if (r.type === 'context') {
      out.push({ old: r, new: r })
      i += 1
      continue
    }
    // Gather a run of removes then a run of adds, and zip them side-by-side.
    const removes: DiffRow[] = []
    const adds: DiffRow[] = []
    while (i < rows.length && rows[i].type === 'remove') removes.push(rows[i++])
    while (i < rows.length && rows[i].type === 'add') adds.push(rows[i++])
    const max = Math.max(removes.length, adds.length)
    for (let k = 0; k < max; k++) {
      out.push({ old: removes[k] ?? null, new: adds[k] ?? null })
    }
  }
  return out
}

function SplitCell({ row }: { row: DiffRow | null }) {
  if (!row) return <div className="flex flex-1 bg-muted/20" />
  const sign = row.type === 'add' ? '+' : row.type === 'remove' ? '-' : ' '
  const no = row.type === 'add' ? row.newNo : row.oldNo
  return (
    <div className={`flex min-w-0 flex-1 ${rowBg(row.type)}`}>
      <LineNo n={no} />
      <span className={`w-4 shrink-0 select-none text-center ${rowText(row.type)}`}>{sign}</span>
      <span className={`min-w-0 whitespace-pre-wrap break-all px-1 ${rowText(row.type)}`}>
        {row.value || ' '}
      </span>
    </div>
  )
}

function SplitHunk({ hunk }: { hunk: DiffHunk }) {
  const rows = toSplitRows(hunk.rows)
  return (
    <>
      <HunkHeader header={hunk.header} />
      {rows.map((r, i) => (
        <div key={i} className="divide-border/50 flex divide-x">
          <SplitCell row={r.old} />
          <SplitCell row={r.new} />
        </div>
      ))}
    </>
  )
}

function FileDiffBlock({ entry, mode }: { entry: SkillFileDiffEntry; mode: DiffViewMode }) {
  const [open, setOpen] = useState(entry.status !== 'unchanged')
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 bg-muted/40 px-3 py-2 text-left transition-colors hover:bg-muted/60"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        )}
        <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate font-mono text-xs text-foreground">
          {entry.path}
        </span>
        <StatusBadge status={entry.status} />
        {(entry.added > 0 || entry.removed > 0) && (
          <span className="flex shrink-0 items-center gap-1.5 font-mono text-[11px]">
            {entry.added > 0 && (
              <span className="text-green-600 dark:text-green-400">+{entry.added}</span>
            )}
            {entry.removed > 0 && (
              <span className="text-red-600 dark:text-red-400">−{entry.removed}</span>
            )}
          </span>
        )}
      </button>
      {open && entry.hunks.length > 0 && (
        <div className="overflow-x-auto border-t border-border bg-background font-mono text-xs leading-relaxed">
          {entry.hunks.map((h, i) =>
            mode === 'split' ? <SplitHunk key={i} hunk={h} /> : <UnifiedHunk key={i} hunk={h} />,
          )}
        </div>
      )}
    </div>
  )
}

export function SkillVersionDiffView({
  diff,
  mode,
}: {
  diff: SkillVersionDiff
  mode: DiffViewMode
}) {
  const { t } = useTranslation()
  const unchangedCount = diff.entries.length - diff.changedCount

  if (diff.changedCount === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-10 text-center">
        <GitCompare className="h-7 w-7 text-muted-foreground/30" />
        <p className="text-sm text-muted-foreground">{t('managed.skills.versionDiffNoChange')}</p>
      </div>
    )
  }

  const changed = diff.entries.filter((e) => e.status !== 'unchanged')

  return (
    <div className="space-y-2.5">
      {changed.map((entry) => (
        <FileDiffBlock key={entry.path} entry={entry} mode={mode} />
      ))}
      {unchangedCount > 0 && (
        <div className="pt-1 text-center text-[11px] text-muted-foreground/60">
          {t('managed.skills.versionDiffUnchangedFiles', { count: unchangedCount })}
        </div>
      )}
    </div>
  )
}
