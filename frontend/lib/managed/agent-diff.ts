/**
 * Field-level diff between two Agent version snapshots.
 *
 * Pure functions, runs entirely client-side — ``list_versions`` already returns
 * every version's full snapshot, so no extra API round-trip is needed.
 */
import { diffLines } from 'diff'

import type { Agent, AgentSkillRef, AgentTool, McpServer } from '@/types/managed'

// ---------- Public diff shape ----------

export type ScalarFieldDiff = {
  changed: boolean
  before: string
  after: string
}

export type ObjectFieldDiff = {
  changed: boolean
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  /** Keys that actually changed (added / removed / value-changed). */
  changedKeys: string[]
}

export type TextLineDiff = { type: 'add' | 'remove' | 'context'; value: string }
export type TextFieldDiff = {
  changed: boolean
  lines: TextLineDiff[]
}

export type ArrayItemDiff<T> = {
  /** Stable identifier used for matching items across versions. */
  key: string
  status: 'added' | 'removed' | 'modified' | 'unchanged'
  before: T | null
  after: T | null
}
export type ArrayFieldDiff<T> = {
  changed: boolean
  items: ArrayItemDiff<T>[]
}

export type AgentDiff = {
  /** Total count of fields that changed. */
  changedCount: number
  engine_kind: ScalarFieldDiff
  description: ScalarFieldDiff
  model: ObjectFieldDiff
  system_prompt: TextFieldDiff
  tools: ArrayFieldDiff<AgentTool>
  mcp_servers: ArrayFieldDiff<McpServer>
  skills: ArrayFieldDiff<AgentSkillRef>
}

// ---------- Helpers ----------

const safeString = (v: unknown): string => (v == null ? '' : String(v))

const stableStringify = (v: unknown): string => {
  if (v == null) return 'null'
  if (typeof v !== 'object') return JSON.stringify(v)
  if (Array.isArray(v)) return '[' + v.map(stableStringify).join(',') + ']'
  const obj = v as Record<string, unknown>
  const keys = Object.keys(obj).sort()
  return '{' + keys.map((k) => JSON.stringify(k) + ':' + stableStringify(obj[k])).join(',') + '}'
}

const deepEqual = (a: unknown, b: unknown): boolean => stableStringify(a) === stableStringify(b)

// ---------- Scalar diff ----------

const diffScalar = (a: unknown, b: unknown): ScalarFieldDiff => {
  const before = safeString(a)
  const after = safeString(b)
  return { changed: before !== after, before, after }
}

// ---------- Object diff (model) ----------

const diffObject = (
  a: Record<string, unknown> | null | undefined,
  b: Record<string, unknown> | null | undefined,
): ObjectFieldDiff => {
  const before = a ?? null
  const after = b ?? null
  if (deepEqual(before, after)) {
    return { changed: false, before, after, changedKeys: [] }
  }
  const keys = new Set<string>([...Object.keys(before || {}), ...Object.keys(after || {})])
  const changedKeys = Array.from(keys).filter(
    (k) => !deepEqual((before || {})[k], (after || {})[k]),
  )
  return { changed: changedKeys.length > 0, before, after, changedKeys }
}

// ---------- Long-text diff (system prompt) ----------

export const diffText = (
  a: string | null | undefined,
  b: string | null | undefined,
): TextFieldDiff => {
  const before = a || ''
  const after = b || ''
  if (before === after) return { changed: false, lines: [] }
  const segments = diffLines(before, after)
  const lines: TextLineDiff[] = []
  for (const seg of segments) {
    const type: TextLineDiff['type'] = seg.added ? 'add' : seg.removed ? 'remove' : 'context'
    // Split multi-line segments into one entry per line so the renderer can mark each line.
    const parts = seg.value.split('\n')
    // diff() emits a trailing newline as an extra empty entry; drop it.
    if (parts[parts.length - 1] === '') parts.pop()
    for (const p of parts) lines.push({ type, value: p })
  }
  return { changed: true, lines }
}

// ---------- Array diff (tools / mcp_servers / skills) ----------

function diffArray<T>(
  a: T[] | null | undefined,
  b: T[] | null | undefined,
  keyOf: (item: T) => string,
): ArrayFieldDiff<T> {
  const aList = a || []
  const bList = b || []
  const beforeMap = new Map<string, T>()
  const afterMap = new Map<string, T>()
  for (const item of aList) beforeMap.set(keyOf(item), item)
  for (const item of bList) afterMap.set(keyOf(item), item)
  const allKeys = new Set<string>([...beforeMap.keys(), ...afterMap.keys()])
  const items: ArrayItemDiff<T>[] = []
  let changed = false
  for (const key of allKeys) {
    const before = beforeMap.get(key) ?? null
    const after = afterMap.get(key) ?? null
    let status: ArrayItemDiff<T>['status']
    if (before == null) status = 'added'
    else if (after == null) status = 'removed'
    else if (!deepEqual(before, after)) status = 'modified'
    else status = 'unchanged'
    if (status !== 'unchanged') changed = true
    items.push({ key, status, before, after })
  }
  // Stable ordering: added/modified first (by key), then removed, then unchanged.
  const order = { added: 0, modified: 1, removed: 2, unchanged: 3 }
  items.sort((x, y) => order[x.status] - order[y.status] || x.key.localeCompare(y.key))
  return { changed, items }
}

const toolKey = (t: AgentTool): string => {
  const name = (t as { name?: string }).name
  const type = (t as { type?: string }).type
  return name || type || JSON.stringify(t).slice(0, 32)
}

const mcpKey = (m: McpServer): string =>
  (m as { name?: string }).name || JSON.stringify(m).slice(0, 32)

const skillKey = (s: AgentSkillRef): string => {
  const sid = (s as { skill_id?: string; name?: string }).skill_id
  const name = (s as { name?: string }).name
  return sid || name || JSON.stringify(s).slice(0, 32)
}

// ---------- Main entry ----------

export function diffAgents(
  base: Agent | null | undefined,
  target: Agent | null | undefined,
): AgentDiff {
  const a = base || ({} as Agent)
  const b = target || ({} as Agent)

  const engine_kind = diffScalar(a.engine_kind, b.engine_kind)
  const description = diffScalar(a.description, b.description)
  const model = diffObject(
    a.model as Record<string, unknown> | null,
    b.model as Record<string, unknown> | null,
  )
  const system_prompt = diffText(a.system || a.system_prompt, b.system || b.system_prompt)
  const tools = diffArray<AgentTool>(a.tools, b.tools, toolKey)
  const mcp_servers = diffArray<McpServer>(a.mcp_servers, b.mcp_servers, mcpKey)
  const skills = diffArray<AgentSkillRef>(a.skills, b.skills, skillKey)

  const changedCount = [
    engine_kind,
    description,
    model,
    system_prompt,
    tools,
    mcp_servers,
    skills,
  ].filter((d) => d.changed).length

  return {
    changedCount,
    engine_kind,
    description,
    model,
    system_prompt,
    tools,
    mcp_servers,
    skills,
  }
}
