/**
 * Client-side ZIP packaging for an AI-authoring skill draft.
 *
 * The AI-authoring workspace edits a purely client-side draft
 * (``{ content, files: {path, content}[] }``) — ``content`` is the SKILL.md
 * body and ``files`` are the rest of the package. "Download" packs that draft
 * into a .zip entirely in the browser (no backend round-trip), laid out the
 * same way the skill import expects: SKILL.md at the root plus every file at
 * its ``path``.
 */
import { zipSync, strToU8 } from 'fflate'

import type { SkillDraft } from '@/hooks/managed/use-skill-authoring'

/** Build the zip bytes for a draft. Exported separately so it can be tested
 * without touching the DOM. */
export function buildDraftZip(draft: SkillDraft): Uint8Array {
  const entries: Record<string, Uint8Array> = {
    'SKILL.md': strToU8(draft.content || ''),
  }
  for (const f of draft.files) {
    // Guard against a stray SKILL.md in files[] clobbering the main doc, and
    // skip entries without a usable path.
    const path = f.path?.trim()
    if (!path || path === 'SKILL.md') continue
    entries[path] = strToU8(f.content || '')
  }
  return zipSync(entries, { level: 6 })
}

/** Safe, filesystem-friendly base name for the downloaded file. */
function zipFileName(name: string): string {
  const base = (name || 'skill').trim().replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '')
  return `${base || 'skill'}.zip`
}

/** Pack the draft and trigger a browser download. Returns the file name used. */
export function downloadDraftZip(draft: SkillDraft): string {
  const bytes = buildDraftZip(draft)
  const fileName = zipFileName(draft.name)
  // Copy into a fresh ArrayBuffer-backed Uint8Array so Blob gets a clean
  // BlobPart regardless of fflate's internal buffer view.
  const blob = new Blob([bytes.slice()], { type: 'application/zip' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
  return fileName
}
