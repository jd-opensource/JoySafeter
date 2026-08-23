/**
 * File-level diff between two Skill version snapshots.
 *
 * Pure functions, runs entirely client-side. Each version's file list comes
 * from ``GET /skills/{id}/versions/{version}/files`` (full snapshot of every
 * file — SKILL.md plus references/, checklists/, ...). We pair files by their
 * full path and use ``structuredPatch`` (jsdiff) to build GitHub-style hunks
 * with @@ headers and surrounding context, so the whole skill package is
 * diffed with unrelated lines collapsed — not just SKILL.md.
 */
import { structuredPatch } from 'diff'

import type { SkillFileRecord, SkillVersionFileRecord } from '@/types/managed'

export type FileDiffStatus = 'added' | 'removed' | 'modified' | 'unchanged'

export type DiffLineType = 'add' | 'remove' | 'context'

/** One rendered row inside a hunk. ``oldNo``/``newNo`` are null on the side
 * that doesn't exist for that row (added rows have no old number, etc.). */
export type DiffRow = {
  type: DiffLineType
  oldNo: number | null
  newNo: number | null
  value: string
}

export type DiffHunk = {
  /** ``@@ -oldStart,oldLines +newStart,newLines @@`` header text. */
  header: string
  rows: DiffRow[]
}

export type SkillFileDiffEntry = {
  /** Full display path, e.g. ``references/adapters/python.yaml`` or ``SKILL.md``. */
  path: string
  status: FileDiffStatus
  added: number
  removed: number
  hunks: DiffHunk[]
}

export type SkillVersionDiff = {
  entries: SkillFileDiffEntry[]
  changedCount: number
  totalAdded: number
  totalRemoved: number
}

type SkillDiffFile = Pick<
  SkillFileRecord | SkillVersionFileRecord,
  'path' | 'file_name' | 'content'
>

const fullPath = (file: SkillDiffFile): string => `${file.path || ''}${file.file_name}`

// Ordering: modified / added / removed first (by path), unchanged last.
const STATUS_ORDER: Record<FileDiffStatus, number> = {
  modified: 0,
  added: 1,
  removed: 2,
  unchanged: 3,
}

/** Build GitHub-style hunks (context-collapsed) for one file's before/after. */
function buildHunks(
  before: string,
  after: string,
): {
  hunks: DiffHunk[]
  added: number
  removed: number
} {
  const patch = structuredPatch('', '', before, after, '', '', { context: 3 })
  const hunks: DiffHunk[] = []
  let added = 0
  let removed = 0

  for (const h of patch.hunks) {
    let oldNo = h.oldStart
    let newNo = h.newStart
    const rows: DiffRow[] = []
    for (const raw of h.lines) {
      const sign = raw[0]
      const value = raw.slice(1)
      // jsdiff appends a "\ No newline at end of file" marker line; skip it.
      if (raw.startsWith('\\')) continue
      if (sign === '+') {
        added += 1
        rows.push({ type: 'add', oldNo: null, newNo, value })
        newNo += 1
      } else if (sign === '-') {
        removed += 1
        rows.push({ type: 'remove', oldNo, newNo: null, value })
        oldNo += 1
      } else {
        rows.push({ type: 'context', oldNo, newNo, value })
        oldNo += 1
        newNo += 1
      }
    }
    hunks.push({
      header: `@@ -${h.oldStart},${h.oldLines} +${h.newStart},${h.newLines} @@`,
      rows,
    })
  }
  return { hunks, added, removed }
}

export function diffSkillVersionFiles(
  base: SkillDiffFile[] | null | undefined,
  target: SkillDiffFile[] | null | undefined,
): SkillVersionDiff {
  const beforeMap = new Map<string, SkillDiffFile>()
  const afterMap = new Map<string, SkillDiffFile>()
  for (const f of base || []) beforeMap.set(fullPath(f), f)
  for (const f of target || []) afterMap.set(fullPath(f), f)

  const allPaths = new Set<string>([...beforeMap.keys(), ...afterMap.keys()])
  const entries: SkillFileDiffEntry[] = []
  let changedCount = 0
  let totalAdded = 0
  let totalRemoved = 0

  for (const path of allPaths) {
    const before = beforeMap.get(path) ?? null
    const after = afterMap.get(path) ?? null
    const beforeContent = before?.content || ''
    const afterContent = after?.content || ''

    let status: FileDiffStatus
    if (before == null) status = 'added'
    else if (after == null) status = 'removed'
    else status = beforeContent === afterContent ? 'unchanged' : 'modified'

    const { hunks, added, removed } = buildHunks(beforeContent, afterContent)

    if (status !== 'unchanged') {
      changedCount += 1
      totalAdded += added
      totalRemoved += removed
    }

    entries.push({ path, status, added, removed, hunks })
  }

  entries.sort(
    (a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status] || a.path.localeCompare(b.path),
  )

  return { entries, changedCount, totalAdded, totalRemoved }
}
