'use client'

import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Activity,
  BookOpenText,
  Brain,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Database,
  FileText,
  GitBranch,
  RefreshCw,
  Search,
  Sparkles,
  UserRound,
  Wrench,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { PageHeader, RelativeTime, ResourceErrorState } from '@/components/managed/shared'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { managedGet, managedPost } from '@/lib/api-client'
import { cn } from '@/lib/utils'

type MemoryKind = 'profile' | 'episode' | 'agent_case' | 'agent_skill'
type ActivityFilter = 'all' | MemoryKind
type ActivityKindFilter = Exclude<ActivityFilter, 'all'>
type ActivityTimeRange = 'daily' | 'weekly' | 'monthly' | 'all'
type EpisodeMetadataFilter =
  | { type: 'user' | 'session'; value: string }
  | { type: 'aggregated' }
  | null
type AgentCaseMetadataFilter = { type: 'agent' | 'session'; value: string } | null
type AgentSkillMetadataFilter = { type: 'agent'; value: string } | null

const ACTIVITY_PAGE_SIZE_OPTIONS = [10, 25, 50]
const DEFAULT_ACTIVITY_PAGE_SIZE = 10
export const MEMORY_OVERVIEW_LIMIT = 500
export const EVEROS_MEMORY_OVERVIEW_REFETCH_INTERVAL_MS = 5000
export const DREAMING_MIN_RUNNING_MS = 700

type PaginationItem = number | 'ellipsis-start' | 'ellipsis-end'

interface EverOSMemoryOverview {
  app_id: string
  project_id: string
  counts: {
    profiles: number
    episodes: number
    agent_cases: number
    agent_skills: number
  }
  profiles: UserProfileMemory[]
  episodes: EpisodeMemory[]
  atomic_facts?: AtomicFactMemory[]
  agent_cases: AgentCaseMemory[]
  agent_skills: AgentSkillMemory[]
  recent_activity: RecentActivity[]
}

interface EverOSMemoryDocument {
  md_path: string
  content: string
}

interface DreamingResponse {
  status: string
  name: string
  display_name: string
  run_id?: string | null
  run_ids?: string[]
}

interface DreamingRunStatus {
  run_id: string
  strategy_name: string
  status: string
  error?: string | null
}

interface UserProfileMemory {
  id: string
  owner_id: string
  summary: string
  explicit_info_json: string
  implicit_traits_json: string
  timestamp_ms: number
  md_path: string
}

interface EpisodeMemory {
  id: string
  entry_id: string
  owner_id: string
  session_id?: string | null
  parent_type?: string | null
  parent_id?: string | null
  source_entry_ids?: string[]
  source_session_ids?: string[]
  source_agent_ids?: string[]
  timestamp: string | null
  subject: string
  summary: string
  episode: string
  md_path: string
}

interface AtomicFactMemory {
  id: string
  entry_id: string
  owner_id: string
  session_id?: string | null
  timestamp: string | null
  parent_type: string
  parent_id?: string | null
  sender_ids?: string[]
  fact: string
  md_path: string
  deprecated_by?: string | null
}

interface AgentCaseMemory {
  id: string
  entry_id: string
  owner_id: string
  session_id: string
  timestamp: string | null
  task_intent: string
  approach: string
  key_insight?: string | null
  quality_score: number
  md_path: string
}

interface AgentSkillMemory {
  id: string
  owner_id: string
  name: string
  description: string
  content: string
  confidence: number
  maturity_score: number
  source_case_ids: string[]
  cluster_id?: string | null
  created_at?: string | null
  updated_at?: string | null
  md_path: string
}

export interface RecentActivity {
  id: string
  kind: MemoryKind
  action: string
  owner_id: string
  session_id?: string | null
  source_entry_ids?: string[]
  source_session_ids?: string[]
  source_agent_ids?: string[]
  timestamp: string | null
  summary: string
  md_path: string
  entry_id?: string | null
  subject?: string | null
  task_intent?: string | null
  name?: string | null
  title?: string
  source_label?: string
}

const kindMeta: Record<MemoryKind, { label: string; tone: string; icon: typeof FileText }> = {
  profile: {
    label: 'Profile',
    tone: 'border-cyan-200 bg-cyan-50 text-cyan-700',
    icon: UserRound,
  },
  episode: {
    label: 'Episode',
    tone: 'border-sky-200 bg-sky-50 text-sky-700',
    icon: BookOpenText,
  },
  agent_case: {
    label: 'Case',
    tone: 'border-amber-200 bg-amber-50 text-amber-700',
    icon: GitBranch,
  },
  agent_skill: {
    label: 'Skill',
    tone: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    icon: Wrench,
  },
}

const activityFilterLabels: Record<ActivityFilter, string> = {
  all: 'Overview',
  profile: 'Profiles',
  episode: 'Episodes',
  agent_case: 'Cases',
  agent_skill: 'Skills',
}

const activityKindLabels: Record<ActivityKindFilter, string> = {
  profile: 'Profile',
  episode: 'Episode',
  agent_case: 'Case',
  agent_skill: 'Skill',
}

const activityTimeRangeLabels: Record<ActivityTimeRange, string> = {
  daily: '当天',
  weekly: '本周',
  monthly: '本月',
  all: '全部时间',
}

const activityFilters: Array<{
  filter: Exclude<ActivityFilter, 'all'>
  label: string
  countKey: keyof EverOSMemoryOverview['counts']
  description: string
  icon: typeof Brain
  className: string
  dotClassName: string
}> = [
  {
    filter: 'profile',
    label: 'Profiles',
    countKey: 'profiles',
    description: '用户画像与长期偏好',
    icon: UserRound,
    className: 'border-cyan-200 bg-cyan-50/40',
    dotClassName: 'bg-cyan-500',
  },
  {
    filter: 'episode',
    label: 'Episodes',
    countKey: 'episodes',
    description: '对话中沉淀的片段',
    icon: BookOpenText,
    className: 'border-sky-200 bg-sky-50/40',
    dotClassName: 'bg-blue-500',
  },
  {
    filter: 'agent_case',
    label: 'Cases',
    countKey: 'agent_cases',
    description: '智能体任务案例',
    icon: GitBranch,
    className: 'border-amber-200 bg-amber-50/40',
    dotClassName: 'bg-amber-500',
  },
  {
    filter: 'agent_skill',
    label: 'Skills',
    countKey: 'agent_skills',
    description: '从案例归纳出的技能',
    icon: Wrench,
    className: 'border-emerald-200 bg-emerald-50/40',
    dotClassName: 'bg-emerald-500',
  },
]

function compactId(value: string | null | undefined) {
  if (!value) return '-'
  return value.length > 16 ? `${value.slice(0, 8)}...${value.slice(-6)}` : value
}

function formatSourceSessionIds(sourceSessionIds: string[] | null | undefined) {
  return (sourceSessionIds || []).filter(Boolean).map(compactId).join('、')
}

function clampPercent(value: number) {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, Math.round(value * 100)))
}

function clampScore(value: number) {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(1, value))
}

function getAgentSkillQualityScore(item: Pick<AgentSkillMemory, 'confidence' | 'maturity_score'>) {
  return clampScore(item.confidence) * 0.7 + clampScore(item.maturity_score) * 0.3
}

function truncate(value: string | null | undefined, length = 180) {
  const text = (value || '').trim()
  if (!text) return '-'
  return text.length > length ? `${text.slice(0, length)}...` : text
}

export function sourceDisplayPath(path: string | null | undefined) {
  const text = (path || '').trim()
  if (!text) return '-'
  const parts = text.split('/').filter(Boolean)
  const userIndex = parts.indexOf('users')
  const agentIndex = parts.indexOf('agents')
  const scopedIndex = [userIndex, agentIndex].filter((index) => index >= 0).sort((a, b) => a - b)[0]
  if (scopedIndex !== undefined) return parts.slice(scopedIndex).join('/')
  return parts.join('/') || text
}

function formatSourceLabel(path: string | null | undefined) {
  const displayPath = sourceDisplayPath(path)
  return displayPath === '-' ? '-' : `源文件：${displayPath}`
}

function activityDetails(item: RecentActivity, overview: EverOSMemoryOverview) {
  if (item.kind === 'episode') {
    const episode = overview.episodes.find((candidate) => (
      candidate.id === item.id || (item.entry_id && candidate.entry_id === item.entry_id)
    ))
    return {
      entry_id: item.entry_id || episode?.entry_id,
      session_id: item.session_id || episode?.session_id,
      subject: item.subject || episode?.subject,
      title: item.subject || episode?.subject || episode?.summary || item.summary,
    }
  }

  if (item.kind === 'agent_case') {
    const agentCase = overview.agent_cases.find((candidate) => (
      candidate.id === item.id || (item.entry_id && candidate.entry_id === item.entry_id)
    ))
    return {
      entry_id: item.entry_id || agentCase?.entry_id,
      session_id: item.session_id || agentCase?.session_id,
      task_intent: item.task_intent || agentCase?.task_intent,
      title: item.task_intent || agentCase?.task_intent || item.summary,
    }
  }

  if (item.kind === 'agent_skill') {
    const skill = overview.agent_skills.find((candidate) => candidate.id === item.id)
    return {
      name: item.name || skill?.name,
      title: item.name || skill?.name || item.summary,
    }
  }

  const profile = overview.profiles.find((candidate) => candidate.id === item.id)
  return {
    title: profile?.summary || item.summary,
  }
}

function activityTitle(item: RecentActivity, overview: EverOSMemoryOverview) {
  if (item.kind === 'episode') {
    if (item.subject) return item.subject
    const episode = overview.episodes.find((candidate) => (
      candidate.id === item.id || (item.entry_id && candidate.entry_id === item.entry_id)
    ))
    return episode?.subject || episode?.summary || item.summary
  }

  if (item.kind === 'agent_case') {
    if (item.task_intent) return item.task_intent
    const agentCase = overview.agent_cases.find((candidate) => (
      candidate.id === item.id || (item.entry_id && candidate.entry_id === item.entry_id)
    ))
    return agentCase?.task_intent || item.summary
  }

  if (item.kind === 'agent_skill') {
    if (item.name) return item.name
    const skill = overview.agent_skills.find((candidate) => candidate.id === item.id)
    return skill?.name || item.summary
  }

  const profile = overview.profiles.find((candidate) => candidate.id === item.id)
  return profile?.summary || item.summary
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function splitMemoryEntryBlocks(content: string) {
  const blocks: Array<{ entryId: string; body: string }> = []
  const entryPattern = /<!--\s*entry:([^\s>]+)\s*-->\s*([\s\S]*?)\s*<!--\s*\/entry:\1\s*-->/g
  let match: RegExpExecArray | null
  while ((match = entryPattern.exec(content)) !== null) {
    blocks.push({ entryId: match[1].trim(), body: match[2].trim() })
  }
  return blocks
}

function normalizedText(value: string | null | undefined) {
  return (value || '').replace(/\s+/g, ' ').trim().toLowerCase()
}

function blockMatchesTitle(block: string, title: string) {
  const normalizedTitle = normalizedText(title)
  if (!normalizedTitle) return false
  const normalizedBlock = normalizedText(block)
  return normalizedBlock.includes(normalizedTitle)
}

function blockSessionId(block: string) {
  const match = block.match(/^\*\*session_id\*\*:\s*(.+)$/im)
  return match?.[1]?.trim() || ''
}

function blockMatchesSession(block: string, sessionId: string | null | undefined) {
  const normalizedSession = normalizedText(sessionId)
  if (!normalizedSession) return false
  const normalizedBlockSession = normalizedText(blockSessionId(block))
  return normalizedBlockSession === normalizedSession || normalizedBlockSession.startsWith(`${normalizedSession}.`)
}

function blockMatchesFocusedEpisode(block: string, item: RecentActivity, title: string) {
  if (blockMatchesSession(block, item.session_id)) return true
  return blockMatchesTitle(block, title)
}

function stripEntryComments(content: string) {
  return content
    .replace(/<!--\s*entry:[\s\S]*?-->/g, '')
    .replace(/<!--\s*\/entry:[\s\S]*?-->/g, '')
    .trim()
}

function stripYamlFrontmatter(content: string) {
  return content.replace(/^---\s*\r?\n[\s\S]*?\r?\n---\s*(?:\r?\n|$)/, '').trim()
}

function removeMemoryMetadataPreamble(content: string) {
  const text = stripYamlFrontmatter(stripEntryComments(content))
  const firstSection = text.search(/^(?:#{2,6}\s*)?(?:Subject|Summary|Content|TaskIntent|Approach|KeyInsight|Name|Description)\s*$/im)
  if (firstSection >= 0) return text.slice(firstSection).trim()

  return text
    .split(/\r?\n/)
    .filter((line) => {
      const trimmed = line.trim()
      if (!trimmed) return true
      if (/^[a-z]+_\d{8}_\d+$/i.test(trimmed)) return false
      if (/^\*\*[a-z_]+\*\*:/i.test(trimmed)) return false
      return true
    })
    .join('\n')
    .trim()
}

export function extractFocusedMemoryBlock(content: string, item: RecentActivity | null) {
  const text = content || ''
  if (!item) return text
  const entryId = item.entry_id?.trim()
  const title = item.subject || item.task_intent || item.name || item.title || item.summary

  if (entryId) {
    const entryBlocks = splitMemoryEntryBlocks(text).filter((block) => block.entryId === entryId)
    const titledEntryBlock = entryBlocks.find((block) => (
      item.kind === 'episode'
        ? blockMatchesFocusedEpisode(block.body, item, title)
        : blockMatchesTitle(block.body, title)
    ))
    if (titledEntryBlock) return titledEntryBlock.body
    if (item.kind === 'episode' && entryBlocks.length > 0) return ''
    if (entryBlocks.length === 1) return entryBlocks[0].body
  }

  const matchedBlock = splitMemoryEntryBlocks(text).find((block) => blockMatchesTitle(block.body, title))
  return matchedBlock?.body || text
}

function episodeFallbackMemoryBlock(episode: EpisodeMemory) {
  return [
    '### Subject',
    episode.subject || 'Episode',
    '',
    '### Summary',
    episode.summary || '',
    '',
    '### Content',
    episode.episode || episode.summary || '',
  ].join('\n').trim()
}

export function parseMemoryBlockSections(content: string) {
  const text = removeMemoryMetadataPreamble(content)
  if (!text) return []

  const headingPattern = /^(?:#{2,6}\s*)?(Subject|Summary|Content|TaskIntent|Approach|KeyInsight|Name|Description)\s*$/gim
  const headings = Array.from(text.matchAll(headingPattern))
  if (!headings.length) {
    return [{ label: '内容', content: cleanMemorySectionContent('Content', text) }]
  }

  return headings
    .map((heading, index) => {
      const label = heading[1].trim()
      const bodyStart = (heading.index || 0) + heading[0].length
      const bodyEnd = index + 1 < headings.length ? headings[index + 1].index || text.length : text.length
      return {
        label,
        content: cleanMemorySectionContent(label, text.slice(bodyStart, bodyEnd).trim()),
      }
    })
    .filter((section) => section.label || section.content)
}

function cleanMemorySectionContent(label: string, content: string) {
  if (label !== 'Content') return content
  const firstMarkdownHeading = content.search(/^#{1,6}\s+\S/m)
  if (firstMarkdownHeading > 0) return content.slice(firstMarkdownHeading).trim()
  return content
}

function parseJsonArray(value: string): unknown[] {
  try {
    const parsed = JSON.parse(value || '[]')
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function formatProfileMemoryItem(item: unknown): { title: string; body: string } {
  if (item === null || item === undefined) return { title: '未命名条目', body: '' }
  if (typeof item !== 'object') return { title: String(item), body: '' }

  const record = item as Record<string, unknown>
  const titleKeys = ['category', 'trait', 'name', 'key', 'type', 'label']
  const bodyKeys = ['description', 'content', 'value', 'evidence', 'reason']
  const title = firstTextValue(record, titleKeys) || '未命名条目'
  const body = firstTextValue(record, bodyKeys) || formatRecordFields(record, [...titleKeys, ...bodyKeys])
  return { title, body }
}

function firstTextValue(record: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  }
  return ''
}

function formatRecordFields(record: Record<string, unknown>, excludedKeys: string[]) {
  const excluded = new Set(excludedKeys)
  return Object.entries(record)
    .filter(([key, value]) => !excluded.has(key) && value !== null && value !== undefined && value !== '')
    .map(([key, value]) => `${key}: ${typeof value === 'object' ? JSON.stringify(value) : String(value)}`)
    .join('\n')
}

function formatTimelineTimestamp(timestamp: string | null | undefined) {
  if (!timestamp) return 'No timestamp'
  const date = new Date(timestamp)
  if (!Number.isFinite(date.getTime())) return 'Invalid time'
  return [
    `${padDatePart(date.getMonth() + 1)}/${padDatePart(date.getDate())}/${date.getFullYear()}`,
    `${padDatePart(date.getHours())}:${padDatePart(date.getMinutes())}:${padDatePart(date.getSeconds())}`,
  ].join(', ')
}

function detailTabForKind(kind: MemoryKind) {
  return kind === 'profile' || kind === 'episode' ? 'users' : 'agents'
}

function matchesFocusedActivity(
  item: { id: string; md_path: string; owner_id?: string | null; entry_id?: string | null },
  focus: RecentActivity | null,
  collectionHasExactMatch: boolean,
) {
  if (!focus) return true
  if (focus.entry_id && item.entry_id) {
    if (item.entry_id !== focus.entry_id) return false
    if (item.md_path && focus.md_path) return item.md_path === focus.md_path
    if (item.owner_id && focus.owner_id) return item.owner_id === focus.owner_id
    return true
  }
  if (item.id === focus.id) return true
  return !collectionHasExactMatch && item.md_path === focus.md_path
}

function matchesTimelineFocus(
  item: { id: string; md_path?: string | null; owner_id?: string | null; entry_id?: string | null },
  focus: RecentActivity | null,
  titles: Array<string | null | undefined>,
) {
  if (!focus) return false
  if (focus.entry_id && item.entry_id) {
    if (item.entry_id !== focus.entry_id) return false
    if (item.md_path && focus.md_path) return item.md_path === focus.md_path
    if (item.owner_id && focus.owner_id) return item.owner_id === focus.owner_id
    return true
  }
  if (item.id === focus.id) return true

  const focusTitle = normalizedText(focus.subject || focus.task_intent || focus.name || focus.title || focus.summary)
  if (!focusTitle) return false
  return titles.some((title) => normalizedText(title) === focusTitle)
}

function filterFocusedMemory<T extends { id: string; md_path: string; owner_id?: string | null; entry_id?: string | null }>(
  items: T[],
  focus: RecentActivity | null,
  kind: MemoryKind,
) {
  if (!focus) return items
  if (focus.kind !== kind) return []
  const hasExactMatch = items.some((item) => (
    item.id === focus.id || (focus.entry_id && item.entry_id === focus.entry_id)
  ))
  return items.filter((item) => matchesFocusedActivity(item, focus, hasExactMatch))
}

function MemoryDocumentSections({
  sections,
  loading,
  error,
  hideGenericContentLabel = false,
}: {
  sections: Array<{ label: string; content: string }>
  loading: boolean
  error: unknown
  hideGenericContentLabel?: boolean
}) {
  return (
    <div className="rounded-md border bg-card p-5 shadow-sm">
      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : error ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          无法加载 md 文档完整内容。
        </div>
      ) : (
        <div className="space-y-5">
          {sections.length ? sections.map((section) => (
            <section key={section.label} className="space-y-1">
              {hideGenericContentLabel && section.label === '内容' ? null : (
                <div className="text-sm font-medium text-muted-foreground">{section.label}</div>
              )}
              <MarkdownContent content={section.content || '-'} />
            </section>
          )) : (
            <div className="text-sm text-muted-foreground">暂无内容</div>
          )}
        </div>
      )}
    </div>
  )
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="prose prose-sm max-w-none break-words text-foreground dark:prose-invert prose-p:leading-7 prose-pre:overflow-x-auto prose-pre:rounded-md prose-pre:border prose-pre:bg-muted prose-pre:p-3 prose-code:rounded prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:font-mono">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {content}
      </ReactMarkdown>
    </div>
  )
}

function AtomicFactsSection({ facts }: { facts: AtomicFactMemory[] }) {
  if (!facts.length) return null

  return (
    <section className="rounded-md border bg-card p-4 shadow-sm">
      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <Sparkles className="h-4 w-4 text-sky-600" />
        关联事实
      </div>
      <ul className="mt-3 divide-y rounded-md border bg-muted/20">
        {facts.map((fact) => (
          <li key={fact.entry_id || fact.id} className="px-3 py-2 text-sm leading-6 text-muted-foreground">
            {fact.fact}
          </li>
        ))}
      </ul>
    </section>
  )
}

function includesQuery(query: string, values: Array<string | number | null | undefined>) {
  if (!query.trim()) return true
  const needle = query.trim().toLowerCase()
  return values.some((value) => String(value ?? '').toLowerCase().includes(needle))
}

function timestampFromMs(value: number | null | undefined) {
  if (!value) return null
  return new Date(value).toISOString()
}

function padDatePart(value: number) {
  return String(value).padStart(2, '0')
}

function getLocalTimeParts(timestamp: string | null | undefined) {
  if (!timestamp) return '00:00:00'
  const date = new Date(timestamp)
  if (!Number.isFinite(date.getTime())) return '00:00:00'
  return [
    padDatePart(date.getHours()),
    padDatePart(date.getMinutes()),
    padDatePart(date.getSeconds()),
  ].join(':')
}

function findMemoryDate(value: string | null | undefined) {
  if (!value) return null
  const dashed = value.match(/\b(20\d{2}-\d{2}-\d{2})\b/)
  if (dashed) return dashed[1]
  const compact = value.match(/\b(20\d{2})(\d{2})(\d{2})\b/)
  if (compact) return `${compact[1]}-${compact[2]}-${compact[3]}`
  return null
}

function getMemoryTimestamp(timestamp: string | null | undefined, mdPath: string | null | undefined, id?: string | null) {
  if (timestamp && Number.isFinite(new Date(timestamp).getTime())) return timestamp

  const memoryDate = findMemoryDate(mdPath) || findMemoryDate(id)
  if (memoryDate) {
    return `${memoryDate}T${getLocalTimeParts(timestamp)}`
  }
  return timestamp
}

export function getActivityTimestamp(item: RecentActivity) {
  return getMemoryTimestamp(item.timestamp, item.md_path, item.id)
}

function episodeToActivity(episode: EpisodeMemory): RecentActivity {
  return {
    id: episode.id,
    entry_id: episode.entry_id,
    kind: 'episode',
    action: 'View',
    owner_id: episode.owner_id,
    session_id: episode.session_id,
    source_entry_ids: episode.source_entry_ids,
    source_session_ids: episode.source_session_ids,
    source_agent_ids: episode.source_agent_ids,
    timestamp: episode.timestamp,
    summary: episode.summary || episode.episode,
    subject: episode.subject,
    title: episode.subject || episode.summary || episode.episode || episode.id,
    md_path: episode.md_path,
  }
}

function profileToActivity(profile: UserProfileMemory): RecentActivity {
  return {
    id: profile.id,
    kind: 'profile',
    action: 'View',
    owner_id: profile.owner_id,
    timestamp: timestampFromMs(profile.timestamp_ms),
    summary: profile.summary,
    title: profile.summary || profile.owner_id || profile.id,
    md_path: profile.md_path,
  }
}

function agentCaseToActivity(item: AgentCaseMemory): RecentActivity {
  return {
    id: item.id,
    entry_id: item.entry_id,
    kind: 'agent_case',
    action: 'View',
    owner_id: item.owner_id,
    session_id: item.session_id,
    timestamp: item.timestamp,
    summary: item.approach || item.key_insight || item.task_intent,
    task_intent: item.task_intent,
    title: item.task_intent || item.approach || item.id,
    md_path: item.md_path,
  }
}

function agentSkillToActivity(item: AgentSkillMemory): RecentActivity {
  return {
    id: item.id,
    kind: 'agent_skill',
    action: 'View',
    owner_id: item.owner_id,
    timestamp: item.updated_at || item.created_at || null,
    summary: item.description || item.content || item.name,
    name: item.name,
    title: item.name || item.description || item.id,
    md_path: item.md_path,
  }
}

export function buildMemoryActivityItems(
  source: Pick<EverOSMemoryOverview, 'profiles' | 'episodes' | 'agent_cases' | 'agent_skills'>,
) {
  return [
    ...source.profiles.map(profileToActivity),
    ...source.episodes.map(episodeToActivity),
    ...source.agent_cases.map(agentCaseToActivity),
    ...source.agent_skills.map(agentSkillToActivity),
  ]
    .map((item) => ({
      ...item,
      source_label: formatSourceLabel(item.md_path),
    }))
    .sort((a, b) => {
      const aTimestamp = getActivityTimestamp(a)
      const bTimestamp = getActivityTimestamp(b)
      const aTime = aTimestamp ? new Date(aTimestamp).getTime() : Number.NaN
      const bTime = bTimestamp ? new Date(bTimestamp).getTime() : Number.NaN
      const aValid = Number.isFinite(aTime)
      const bValid = Number.isFinite(bTime)

      if (aValid && bValid) return bTime - aTime
      if (aValid) return -1
      if (bValid) return 1
      return a.kind.localeCompare(b.kind) || a.id.localeCompare(b.id)
    })
}

function formatActivityTimestamp(timestamp: string | null | undefined) {
  if (!timestamp) return 'No timestamp'
  const date = new Date(timestamp)
  if (!Number.isFinite(date.getTime())) return 'Invalid time'
  return [
    `${date.getFullYear()}-${padDatePart(date.getMonth() + 1)}-${padDatePart(date.getDate())}`,
    `${padDatePart(date.getHours())}:${padDatePart(date.getMinutes())}`,
  ].join(' ')
}

function formatActivityAction(action: string | null | undefined) {
  const text = (action || '').trim()
  if (!text) return '-'
  return text.charAt(0).toUpperCase() + text.slice(1).toLowerCase()
}

export function isWithinTimeRange(timestamp: string | null | undefined, range: ActivityTimeRange, now = new Date()) {
  if (range === 'all') return true
  if (!timestamp) return false

  const time = new Date(timestamp).getTime()
  if (!Number.isFinite(time)) return false

  const date = new Date(time)
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())

  if (range === 'daily') {
    const startOfTomorrow = new Date(startOfToday)
    startOfTomorrow.setDate(startOfTomorrow.getDate() + 1)
    return date >= startOfToday && date < startOfTomorrow
  }

  if (range === 'weekly') {
    const day = startOfToday.getDay()
    const daysSinceMonday = day === 0 ? 6 : day - 1
    const startOfWeek = new Date(startOfToday)
    startOfWeek.setDate(startOfWeek.getDate() - daysSinceMonday)
    const startOfNextWeek = new Date(startOfWeek)
    startOfNextWeek.setDate(startOfNextWeek.getDate() + 7)
    return date >= startOfWeek && date < startOfNextWeek
  }

  const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1)
  const startOfNextMonth = new Date(now.getFullYear(), now.getMonth() + 1, 1)
  return date >= startOfMonth && date < startOfNextMonth
}

function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-md border border-dashed bg-muted/20 px-6 py-10 text-center">
      <Database className="mx-auto h-8 w-8 text-muted-foreground" />
      <div className="mt-3 text-sm font-medium text-foreground">{title}</div>
      <div className="mt-1 text-sm text-muted-foreground">{description}</div>
    </div>
  )
}

function LoadingState() {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-28 rounded-md" />
        ))}
      </div>
      <Skeleton className="h-80 rounded-md" />
    </div>
  )
}

function MetricCard({
  label,
  value,
  description,
  icon: Icon,
  className,
  active,
  onClick,
}: {
  label: string
  value: number
  description: string
  icon: typeof Brain
  className: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      aria-label={`Filter recent activity by ${label}`}
      onClick={onClick}
      className={cn(
        'rounded-md border bg-card p-4 text-left transition-colors hover:border-foreground/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        active && 'ring-2 ring-ring ring-offset-2',
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-muted-foreground">{label}</div>
          <div className="mt-2 text-3xl font-semibold text-foreground">{value}</div>
        </div>
        <div className="rounded-md border bg-background p-2">
          <Icon className="h-4 w-4 text-foreground" />
        </div>
      </div>
      <div className="mt-3 text-xs text-muted-foreground">{description}</div>
    </button>
  )
}

function ActivityList({
  items,
  onOpenDetail,
  emptyTitle = '暂无近期记忆活动',
  emptyDescription = '写入记忆后会在这里形成时间线。',
}: {
  items: RecentActivity[]
  onOpenDetail: (item: RecentActivity) => void
  emptyTitle?: string
  emptyDescription?: string
}) {
  if (!items.length) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />
  }

  return (
    <div className="overflow-hidden rounded-md border bg-card">
      <div className="overflow-x-auto">
        <table className="w-full table-fixed text-sm">
          <colgroup>
            <col className="w-[170px]" />
            <col className="w-[100px]" />
            <col className="w-[130px]" />
            <col />
            <col className="w-[90px]" />
          </colgroup>
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="px-4 py-3 font-medium">时间</th>
              <th className="px-4 py-3 font-medium">操作</th>
              <th className="px-4 py-3 font-medium">记忆类型</th>
              <th className="px-4 py-3 font-medium">标题</th>
              <th className="px-4 py-3 text-right font-medium">详情</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => {
              const meta = kindMeta[item.kind]
              const activityTimestamp = getActivityTimestamp(item)
              return (
                <tr key={`${item.kind}-${item.id}-${item.entry_id || item.md_path || index}`} className="border-b last:border-b-0">
                  <td className="whitespace-nowrap px-4 py-4 text-muted-foreground">
                    {activityTimestamp ? (
                      <time dateTime={activityTimestamp}>{formatActivityTimestamp(activityTimestamp)}</time>
                    ) : (
                      'No timestamp'
                    )}
                  </td>
                  <td className="px-4 py-4 text-foreground">{formatActivityAction(item.action)}</td>
                  <td className="px-4 py-4">
                    <Badge variant="outline" className={cn('rounded-md px-3 py-0.5 font-medium', meta.tone)}>
                      {meta.label}
                    </Badge>
                  </td>
                  <td className="min-w-0 px-4 py-4">
                    <div className="truncate font-medium text-foreground" title={item.title || item.summary}>
                      {truncate(item.title || item.summary, 90)}
                    </div>
                    <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground" title={item.md_path}>
                      {item.source_label || formatSourceLabel(item.md_path)}
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-4 text-right">
                    <button
                      type="button"
                      className="font-medium text-amber-500 transition-colors hover:text-amber-600"
                      title={item.md_path || item.id}
                      onClick={() => onOpenDetail(item)}
                    >
                      详情
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ActivityTypeFilter({
  selectedKinds,
  onToggle,
}: {
  selectedKinds: ActivityKindFilter[]
  onToggle: (kind: ActivityKindFilter) => void
}) {
  const selectedSet = new Set(selectedKinds)
  const triggerLabel =
    selectedKinds.length === 0
      ? 'All Types'
      : selectedKinds.length === 1
        ? activityKindLabels[selectedKinds[0]]
        : `${selectedKinds.length} Types`

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-label="Filter memory activity by type"
          className="min-w-[118px] justify-between"
        >
          {triggerLabel}
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-36">
        {activityFilters.map((item) => (
          <DropdownMenuCheckboxItem
            key={item.filter}
            checked={selectedSet.has(item.filter)}
            onCheckedChange={() => onToggle(item.filter)}
            className={cn(
              'pl-9',
              '[&>span:first-child]:h-4 [&>span:first-child]:w-4 [&>span:first-child]:rounded-[4px] [&>span:first-child]:border [&>span:first-child]:border-input [&>span:first-child]:bg-background [&>span:first-child]:text-primary-foreground',
              '[&[data-state=checked]>span:first-child]:border-primary [&[data-state=checked]>span:first-child]:bg-primary',
              '[&>span:first-child_svg]:h-3 [&>span:first-child_svg]:w-3',
            )}
          >
            <span className="flex items-center gap-2">
              <span className={cn('h-2 w-2 rounded-full', item.dotClassName)} />
              {activityKindLabels[item.filter]}
            </span>
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function ActivityPagination({
  page,
  pageCount,
  pageSize,
  pageSizeOptions,
  onPageChange,
  onPageSizeChange,
}: {
  page: number
  pageCount: number
  pageSize: number
  pageSizeOptions: number[]
  onPageChange: (page: number) => void
  onPageSizeChange: (pageSize: number) => void
}) {
  if (pageCount <= 1 && pageSizeOptions.length <= 1) return null

  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label="Previous page"
          disabled={page <= 1}
          onClick={() => onPageChange(Math.max(1, page - 1))}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <div className="flex items-center gap-1 rounded-lg bg-muted p-1">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            aria-label={`Go to page ${page}`}
            aria-current="page"
            className="h-7 min-w-7 px-2"
            disabled
          >
            {page}
          </Button>
        </div>
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label="Next page"
          disabled={page >= pageCount}
          onClick={() => onPageChange(Math.min(pageCount, page + 1))}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
      <div className="ml-auto flex items-center gap-1 rounded-lg bg-muted p-1">
        {pageSizeOptions.map((size) => {
          const isActive = size === pageSize
          return (
            <Button
              key={size}
              type="button"
              variant={isActive ? 'default' : 'ghost'}
              size="sm"
              aria-label={`Show ${size} per page`}
              aria-current={isActive ? 'page' : undefined}
              className="h-8 px-3"
              onClick={() => onPageSizeChange(size)}
              disabled={isActive}
            >
              {size}
            </Button>
          )
        })}
      </div>
    </div>
  )
}

export function getPaginationItems(page: number, pageCount: number): PaginationItem[] {
  if (pageCount <= 7) {
    return Array.from({ length: pageCount }, (_, index) => index + 1)
  }

  const currentPage = Math.max(1, Math.min(page, pageCount))
  const pageNumbers = new Set<number>([1, 2, 3, pageCount - 2, pageCount - 1, pageCount])

  for (let number = currentPage - 1; number <= currentPage + 1; number += 1) {
    if (number >= 1 && number <= pageCount) {
      pageNumbers.add(number)
    }
  }

  const sortedPages = Array.from(pageNumbers).sort((a, b) => a - b)
  const items: PaginationItem[] = []

  sortedPages.forEach((number, index) => {
    if (index > 0 && number - sortedPages[index - 1] > 1) {
      const marker = number <= currentPage ? 'ellipsis-start' : 'ellipsis-end'
      if (!items.includes(marker)) {
        items.push(marker)
      }
    }
    items.push(number)
  })

  return items
}

function ActivityTimeFilter({
  value,
  onChange,
}: {
  value: ActivityTimeRange
  onChange: (value: ActivityTimeRange) => void
}) {
  return (
    <Tabs value={value} onValueChange={(next) => onChange(next as ActivityTimeRange)}>
      <TabsList className="h-9">
        {Object.entries(activityTimeRangeLabels).map(([range, label]) => (
          <TabsTrigger key={range} value={range} className="h-7 px-2.5 text-xs">
            {label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  )
}

function ProfileCard({
  profile,
  focusedActivity,
  selected = false,
  document,
  loading = false,
  error = null,
  onClear,
  onSelect,
  onOpenDetail,
}: {
  profile: UserProfileMemory
  focusedActivity?: RecentActivity | null
  selected?: boolean
  document?: EverOSMemoryDocument
  loading?: boolean
  error?: unknown
  onClear?: () => void
  onSelect?: (profile: UserProfileMemory) => void
  onOpenDetail?: (profile: UserProfileMemory) => void
}) {
  const timestamp = timestampFromMs(profile.timestamp_ms)
  const isFocused = matchesTimelineFocus(profile, focusedActivity || null, [profile.summary, profile.owner_id])
  const focusedBlock = isFocused ? extractFocusedMemoryBlock(document?.content || '', profileToActivity(profile)) : ''
  const focusedSections = isFocused ? parseMemoryBlockSections(focusedBlock) : []
  const explicitInfo = isFocused ? parseJsonArray(profile.explicit_info_json).map(formatProfileMemoryItem) : []
  const implicitTraits = isFocused ? parseJsonArray(profile.implicit_traits_json).map(formatProfileMemoryItem) : []

  return (
    <div
      className={cn(
        'relative rounded-md border bg-card p-4 transition-colors hover:border-foreground/30',
        selected && 'border-cyan-400 bg-cyan-50/40 ring-2 ring-cyan-200 ring-offset-1',
      )}
    >
      <div
        role="button"
        tabIndex={0}
        aria-pressed={selected}
        aria-label={`选择 Profile User ${profile.owner_id}`}
        onClick={() => onSelect?.(profile)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            onSelect?.(profile)
          }
        }}
        className="rounded-sm pr-10 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <UserRound className="h-4 w-4 text-cyan-600" />
              <div className="truncate text-sm font-semibold text-foreground">User {compactId(profile.owner_id)}</div>
            </div>
            {timestamp ? <div className="mt-1 text-xs text-muted-foreground"><RelativeTime date={timestamp} /></div> : null}
          </div>
          <Badge variant="outline" className="border-cyan-200 bg-cyan-50 text-cyan-700">Profile</Badge>
        </div>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">{truncate(profile.summary, 260)}</p>
      </div>
      {isFocused && onClear ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="收起 Profile 详情"
          onClick={(event) => {
            event.stopPropagation()
            onClear?.()
          }}
          className="absolute right-4 top-4 h-7 w-7 text-muted-foreground"
        >
          <ChevronDown className="h-4 w-4" />
        </Button>
      ) : (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="展开 Profile 详情"
          className="absolute right-4 top-4 h-7 w-7 text-muted-foreground"
          onClick={(event) => {
            event.stopPropagation()
            onOpenDetail?.(profile)
          }}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      )}
      {isFocused ? (
        <div className="mt-4 max-h-[520px] space-y-4 overflow-y-auto pr-2">
          <ProfileMemorySection title="显式信息" items={explicitInfo} />
          <ProfileMemorySection title="隐式特征" items={implicitTraits} />
          {focusedSections.length || loading || error ? (
            <MemoryDocumentSections
              sections={focusedSections}
              loading={loading}
              error={error}
              hideGenericContentLabel
            />
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function ProfileMemorySection({
  title,
  items,
}: {
  title: string
  items: Array<{ title: string; body: string }>
}) {
  return (
    <section className="space-y-2 border-t pt-3">
      <div className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">{title}</div>
      {items.length ? (
        <div className="space-y-2">
          {items.map((item, index) => (
            <div key={`${title}-${index}`} className="rounded-md border bg-muted/20 px-3 py-2">
              <div className="text-sm font-medium text-foreground">{item.title}</div>
              {item.body ? <div className="mt-1 whitespace-pre-wrap text-sm leading-6 text-muted-foreground">{item.body}</div> : null}
            </div>
          ))}
        </div>
      ) : (
        <div className="text-sm text-muted-foreground">暂无内容</div>
      )}
    </section>
  )
}

function EpisodeTimeline({
  episodes,
  atomicFacts = [],
  focusedActivity,
  document,
  loading = false,
  error = null,
  autoScrollFocused = false,
  disableUnfocusedExpand = false,
  onClear,
  onOpenDetail,
  onFilter,
}: {
  episodes: EpisodeMemory[]
  atomicFacts?: AtomicFactMemory[]
  focusedActivity?: RecentActivity | null
  document?: EverOSMemoryDocument
  loading?: boolean
  error?: unknown
  autoScrollFocused?: boolean
  disableUnfocusedExpand?: boolean
  onClear?: () => void
  onOpenDetail?: (episode: EpisodeMemory) => void
  onFilter?: (filter: Exclude<EpisodeMetadataFilter, null>) => void
}) {
  const focusedItemRef = useRef<HTMLElement | null>(null)
  const hasFocusedActivity = !!focusedActivity

  useEffect(() => {
    if (!autoScrollFocused || !hasFocusedActivity) return
    focusedItemRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
  }, [autoScrollFocused, hasFocusedActivity, focusedActivity?.entry_id, focusedActivity?.id])

  if (!episodes.length) {
    return <EmptyState title="暂无 Episode" description="沙箱会话产生可沉淀内容后会写入会话片段。" />
  }

  return (
    <div data-testid="user-episode-timeline" className="rounded-md bg-muted/30 px-4 py-4">
      <div className="relative space-y-5 pl-7">
        <div className="absolute bottom-0 left-2.5 top-3 w-px bg-border" />
        {episodes.map((episode) => {
          const timestamp = getMemoryTimestamp(episode.timestamp, episode.md_path, episode.id)
          const isAggregatedEpisode = episode.parent_type === 'cluster'
          const sourceSessionIds = episode.source_session_ids || []
          const sourceSessionLabel = formatSourceSessionIds(sourceSessionIds)
          const isFocused = matchesTimelineFocus(episode, focusedActivity || null, [episode.subject, episode.summary])
          const rowActivity = episodeToActivity(episode)
          const focusedBlock = isFocused
            ? extractFocusedMemoryBlock(document?.content || '', rowActivity) || episodeFallbackMemoryBlock(episode)
            : ''
          const focusedSections = isFocused ? parseMemoryBlockSections(focusedBlock) : []
          const relatedFacts = isFocused ? atomicFacts.filter((fact) => (
            fact.parent_type === 'episode'
            && fact.parent_id === episode.entry_id
            && !fact.deprecated_by
          )) : []
          return (
            <article
              key={`${episode.id}-${episode.entry_id || episode.md_path}`}
              ref={isFocused ? focusedItemRef : undefined}
              className="relative"
            >
              <span className="absolute -left-[22px] top-1.5 h-3 w-3 rounded-full bg-amber-500" />
              <div className="flex items-start justify-between gap-3">
                <time className="text-xs text-muted-foreground" dateTime={timestamp || undefined}>
                  {formatTimelineTimestamp(timestamp)}
                </time>
                {isFocused && onClear ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label="收起 Episode 详情"
                    className="h-7 w-7 shrink-0 text-muted-foreground"
                    onClick={onClear}
                  >
                    <ChevronDown className="h-4 w-4" />
                  </Button>
                ) : disableUnfocusedExpand && focusedActivity ? null : (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label="展开 Episode 详情"
                    className="h-7 w-7 shrink-0 text-muted-foreground"
                    onClick={() => onOpenDetail?.(episode)}
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                )}
              </div>
              <h3 className="mt-2 text-sm font-semibold leading-6 text-foreground">
                {episode.subject || 'Episode'}
              </h3>
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  aria-label={`按用户筛选 ${episode.owner_id}`}
                  onClick={() => onFilter?.({ type: 'user', value: episode.owner_id })}
                  className="rounded-md border bg-background px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                >
                  user ID: {compactId(episode.owner_id)}
                </button>
                {episode.session_id ? (
                  <button
                    type="button"
                    aria-label={`按会话筛选 ${episode.session_id}`}
                    onClick={() => onFilter?.({ type: 'session', value: episode.session_id || '' })}
                    className="rounded-md border bg-background px-2.5 py-1 text-xs text-foreground transition-colors hover:border-foreground/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  >
                    session ID: {compactId(episode.session_id)}
                  </button>
                ) : isAggregatedEpisode ? (
                  <>
                    {sourceSessionLabel ? (
                      <span
                        title={sourceSessionIds.join('、')}
                        className="rounded-md border bg-background px-2.5 py-1 text-xs text-foreground"
                      >
                        来源会话: {sourceSessionLabel}
                      </span>
                    ) : null}
                    <button
                      type="button"
                      aria-label="筛选聚合记忆"
                      onClick={() => onFilter?.({ type: 'aggregated' })}
                      className="inline-flex items-center gap-1 rounded-md border border-cyan-200 bg-cyan-50 px-2.5 py-1 text-xs font-medium text-cyan-700 transition-colors hover:border-cyan-300 hover:bg-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                    >
                      <GitBranch className="h-3 w-3" />
                      聚合记忆
                    </button>
                  </>
                ) : null}
              </div>
              {isFocused ? (
                <div className="mt-3 max-h-[420px] space-y-4 overflow-y-auto pr-2">
                  <MemoryDocumentSections sections={focusedSections} loading={loading} error={error} />
                  <AtomicFactsSection facts={relatedFacts} />
                </div>
              ) : null}
            </article>
          )
        })}
      </div>
    </div>
  )
}

function EpisodeMetadataFilterChip({
  filter,
  onClear,
}: {
  filter: EpisodeMetadataFilter
  onClear: () => void
}) {
  if (!filter) return null

  return (
    <div className="flex items-center gap-1 rounded-md bg-cyan-500 px-2.5 py-1 text-xs font-medium text-cyan-950">
      <span>{filter.type === 'aggregated' ? 'aggregated: 聚合记忆' : `${filter.type}: ${compactId(filter.value)}`}</span>
      <button
        type="button"
        aria-label="清除 Episode 筛选"
        onClick={onClear}
        className="rounded-sm p-0.5 text-cyan-950 transition-colors hover:bg-cyan-600/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  )
}

function AgentCaseTimeline({
  cases,
  focusedActivity,
  document,
  loading = false,
  error = null,
  autoScrollFocused = false,
  disableUnfocusedExpand = false,
  onClear,
  onOpenDetail,
  onFilter,
}: {
  cases: AgentCaseMemory[]
  focusedActivity?: RecentActivity | null
  document?: EverOSMemoryDocument
  loading?: boolean
  error?: unknown
  autoScrollFocused?: boolean
  disableUnfocusedExpand?: boolean
  onClear?: () => void
  onOpenDetail?: (item: AgentCaseMemory) => void
  onFilter?: (filter: Exclude<AgentCaseMetadataFilter, null>) => void
}) {
  const focusedItemRef = useRef<HTMLElement | null>(null)
  const hasFocusedActivity = !!focusedActivity

  useEffect(() => {
    if (!autoScrollFocused || !hasFocusedActivity) return
    focusedItemRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
  }, [autoScrollFocused, hasFocusedActivity, focusedActivity?.entry_id, focusedActivity?.id])

  if (!cases.length) {
    return <EmptyState title="暂无 Agent Case" description="智能体完成任务并同步轨迹后会生成案例记忆。" />
  }

  return (
    <div data-testid="agent-case-timeline" className="rounded-md bg-muted/30 px-4 py-4">
      <div className="relative space-y-5 pl-7">
        <div className="absolute bottom-0 left-2.5 top-3 w-px bg-border" />
        {cases.map((item) => {
          const timestamp = getMemoryTimestamp(item.timestamp, item.md_path, item.id)
          const isFocused = matchesTimelineFocus(item, focusedActivity || null, [item.task_intent, item.approach, item.key_insight])
          const rowActivity = agentCaseToActivity(item)
          const focusedBlock = isFocused ? extractFocusedMemoryBlock(document?.content || '', rowActivity) : ''
          const focusedSections = isFocused ? parseMemoryBlockSections(focusedBlock) : []
          return (
            <article
              key={`${item.id}-${item.entry_id || item.md_path}`}
              ref={isFocused ? focusedItemRef : undefined}
              className="relative"
            >
              <span className="absolute -left-[22px] top-1.5 h-3 w-3 rounded-full bg-amber-500" />
              <div className="flex items-start justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <time className="text-xs text-muted-foreground" dateTime={timestamp || undefined}>
                    {formatTimelineTimestamp(timestamp)}
                  </time>
                  <Badge variant="outline" className="rounded-md border-amber-200 bg-amber-50 px-2 py-0 text-[11px] text-amber-700">
                    质量 {clampPercent(item.quality_score)}%
                  </Badge>
                </div>
                {isFocused && onClear ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label="收起 Case 详情"
                    className="h-7 w-7 shrink-0 text-muted-foreground"
                    onClick={onClear}
                  >
                    <ChevronDown className="h-4 w-4" />
                  </Button>
                ) : disableUnfocusedExpand && focusedActivity ? null : (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label="展开 Case 详情"
                    className="h-7 w-7 shrink-0 text-muted-foreground"
                    onClick={() => onOpenDetail?.(item)}
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                )}
              </div>
              <h3 className="mt-2 text-sm font-semibold leading-6 text-foreground">
                {item.task_intent || 'Agent Case'}
              </h3>
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  aria-label={`按智能体筛选 ${item.owner_id}`}
                  onClick={() => onFilter?.({ type: 'agent', value: item.owner_id })}
                  className="rounded-md border bg-background px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                >
                  agent ID: {compactId(item.owner_id)}
                </button>
                {item.session_id ? (
                  <button
                    type="button"
                    aria-label={`按会话筛选 ${item.session_id}`}
                    onClick={() => onFilter?.({ type: 'session', value: item.session_id })}
                    className="rounded-md border bg-background px-2.5 py-1 text-xs text-foreground transition-colors hover:border-foreground/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  >
                    session ID: {compactId(item.session_id)}
                  </button>
                ) : null}
              </div>
              {isFocused ? (
                <div className="mt-3 max-h-[420px] overflow-y-auto pr-2">
                  <MemoryDocumentSections sections={focusedSections} loading={loading} error={error} />
                </div>
              ) : null}
            </article>
          )
        })}
      </div>
    </div>
  )
}

function AgentCaseMetadataFilterChip({
  filter,
  onClear,
}: {
  filter: AgentCaseMetadataFilter
  onClear: () => void
}) {
  if (!filter) return null

  return (
    <div className="flex items-center gap-1 rounded-md bg-amber-500 px-2.5 py-1 text-xs font-medium text-amber-950">
      <span>{filter.type}: {compactId(filter.value)}</span>
      <button
        type="button"
        aria-label="清除 Agent Case 筛选"
        onClick={onClear}
        className="rounded-sm p-0.5 text-amber-950 transition-colors hover:bg-amber-600/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  )
}

function AgentSkillCard({
  item,
  focusedActivity,
  selected = false,
  document,
  loading = false,
  error = null,
  onClear,
  onSelect,
  onOpenDetail,
  onFilter,
}: {
  item: AgentSkillMemory
  focusedActivity?: RecentActivity | null
  selected?: boolean
  document?: EverOSMemoryDocument
  loading?: boolean
  error?: unknown
  onClear?: () => void
  onSelect?: (item: AgentSkillMemory) => void
  onOpenDetail?: (item: AgentSkillMemory) => void
  onFilter?: (filter: Exclude<AgentSkillMetadataFilter, null>) => void
}) {
  const isFocused = matchesTimelineFocus(item, focusedActivity || null, [item.name, item.description])
  const focusedBlock = isFocused ? extractFocusedMemoryBlock(document?.content || '', agentSkillToActivity(item)) : ''
  const focusedSections = isFocused ? parseMemoryBlockSections(focusedBlock) : []
  const qualityPercent = clampPercent(getAgentSkillQualityScore(item))

  return (
    <div
      className={cn(
        'relative rounded-md border bg-card p-4 transition-colors hover:border-foreground/30',
        selected && 'border-emerald-400 bg-emerald-50/40 ring-2 ring-emerald-200 ring-offset-1',
      )}
    >
      <div
        role="button"
        tabIndex={0}
        aria-pressed={selected}
        aria-label={`选择 Agent Skill ${item.name || item.id}`}
        onClick={() => onSelect?.(item)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            onSelect?.(item)
          }
        }}
        className="rounded-sm pr-12 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Sparkles className="h-4 w-4 text-emerald-600" />
            <h3 className="truncate text-sm font-semibold text-foreground">{item.name || 'Unnamed skill'}</h3>
            <Badge variant="outline" className="rounded-md border-emerald-200 bg-emerald-50 px-2 py-0 text-[11px] text-emerald-700">
              质量 {qualityPercent}%
            </Badge>
          </div>
          <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-muted-foreground">
            {item.description || item.content || '-'}
          </p>
        </div>
      </div>
        {isFocused && onClear ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="收起 Skill 详情"
            onClick={(event) => {
              event.stopPropagation()
              onClear?.()
            }}
            className="absolute right-4 top-4 h-7 w-7 text-muted-foreground"
          >
            <ChevronDown className="h-4 w-4" />
          </Button>
        ) : (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="展开 Skill 详情"
            className="absolute right-4 top-4 h-7 w-7 text-muted-foreground"
            onClick={(event) => {
              event.stopPropagation()
              onOpenDetail?.(item)
            }}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        )}
      <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
        <button
          type="button"
          aria-label={`按智能体筛选 ${item.owner_id}`}
          onClick={() => onFilter?.({ type: 'agent', value: item.owner_id })}
          className="rounded-md border bg-background px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          agent ID: {compactId(item.owner_id)}
        </button>
      </div>
      {isFocused ? (
        <div className="mt-3 max-h-[420px] overflow-y-auto pr-2">
          <MemoryDocumentSections
            sections={focusedSections}
            loading={loading}
            error={error}
            hideGenericContentLabel
          />
        </div>
      ) : null}
    </div>
  )
}

function AgentSkillMetadataFilterChip({
  filter,
  onClear,
}: {
  filter: AgentSkillMetadataFilter
  onClear: () => void
}) {
  if (!filter) return null

  return (
    <div className="flex items-center gap-1 rounded-md bg-emerald-500 px-2.5 py-1 text-xs font-medium text-emerald-950">
      <span>{filter.type}: {compactId(filter.value)}</span>
      <button
        type="button"
        aria-label="清除 Agent Skill 筛选"
        onClick={onClear}
        className="rounded-sm p-0.5 text-emerald-950 transition-colors hover:bg-emerald-600/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  )
}

export default function MemoryStoreListPage() {
  const [searchQuery, setSearchQuery] = useState('')
  const [tab, setTab] = useState('overview')
  const [activityFilter, setActivityFilter] = useState<ActivityFilter>('all')
  const [selectedActivityKinds, setSelectedActivityKinds] = useState<ActivityKindFilter[]>([])
  const [activityTimeRange, setActivityTimeRange] = useState<ActivityTimeRange>('all')
  const [activityPage, setActivityPage] = useState(1)
  const [activityPageSize, setActivityPageSize] = useState(DEFAULT_ACTIVITY_PAGE_SIZE)
  const [profilePage, setProfilePage] = useState(1)
  const [profilePageSize, setProfilePageSize] = useState(DEFAULT_ACTIVITY_PAGE_SIZE)
  const [episodePage, setEpisodePage] = useState(1)
  const [episodePageSize, setEpisodePageSize] = useState(DEFAULT_ACTIVITY_PAGE_SIZE)
  const [agentCasePage, setAgentCasePage] = useState(1)
  const [agentCasePageSize, setAgentCasePageSize] = useState(DEFAULT_ACTIVITY_PAGE_SIZE)
  const [agentSkillPage, setAgentSkillPage] = useState(1)
  const [agentSkillPageSize, setAgentSkillPageSize] = useState(DEFAULT_ACTIVITY_PAGE_SIZE)
  const [focusedActivity, setFocusedActivity] = useState<RecentActivity | null>(null)
  const [expandedProfileActivity, setExpandedProfileActivity] = useState<RecentActivity | null>(null)
  const [expandedEpisodeActivity, setExpandedEpisodeActivity] = useState<RecentActivity | null>(null)
  const [expandedAgentCaseActivity, setExpandedAgentCaseActivity] = useState<RecentActivity | null>(null)
  const [expandedAgentSkillActivity, setExpandedAgentSkillActivity] = useState<RecentActivity | null>(null)
  const [lockedDetailKind, setLockedDetailKind] = useState<MemoryKind | null>(null)
  const [episodeMetadataFilter, setEpisodeMetadataFilter] = useState<EpisodeMetadataFilter>(null)
  const [agentCaseMetadataFilter, setAgentCaseMetadataFilter] = useState<AgentCaseMetadataFilter>(null)
  const [agentSkillMetadataFilter, setAgentSkillMetadataFilter] = useState<AgentSkillMetadataFilter>(null)
  const [dreamingRunId, setDreamingRunId] = useState<string | null>(null)
  const [dreamingStartedAt, setDreamingStartedAt] = useState<number | null>(null)
  const [dreamingTerminalReady, setDreamingTerminalReady] = useState(false)

  const { data, isLoading, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['everos-memory-overview'],
    queryFn: () => managedGet<EverOSMemoryOverview>(`/everos_memory/overview?limit=${MEMORY_OVERVIEW_LIMIT}`),
    refetchInterval: EVEROS_MEMORY_OVERVIEW_REFETCH_INTERVAL_MS,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: 'always',
    staleTime: 0,
  })
  const dreamingMutation = useMutation({
    mutationFn: () => managedPost<DreamingResponse>('/everos_memory/dreaming', { timeout: 120 }),
    onMutate: () => {
      setDreamingRunId(null)
      setDreamingStartedAt(Date.now())
      setDreamingTerminalReady(false)
    },
    onSuccess: (response) => {
      setDreamingRunId(response.run_id ?? response.run_ids?.[0] ?? null)
      void refetch()
    },
  })
  const {
    data: dreamingRunStatus,
    isError: isDreamingRunStatusError,
  } = useQuery({
    queryKey: ['everos-memory-dreaming-run', dreamingRunId],
    queryFn: () => {
      if (!dreamingRunId) throw new Error('Dreaming run id is missing')
      return managedGet<DreamingRunStatus>(`/everos_memory/dreaming/runs/${dreamingRunId}`)
    },
    enabled: Boolean(dreamingRunId),
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 2000 : false),
    refetchOnWindowFocus: true,
  })
  const dreamingRunState = dreamingRunStatus?.status
  const dreamingRunIsTerminal = ['success', 'failed', 'dead_letter', 'crashed'].includes(dreamingRunState || '')
  const displayedDreamingRunStatus = dreamingRunStatus
    ? (
      dreamingRunIsTerminal && !dreamingTerminalReady
        ? { ...dreamingRunStatus, status: 'running' }
        : dreamingRunStatus
    )
    : (
      dreamingRunId && !isDreamingRunStatusError
        ? { run_id: dreamingRunId, strategy_name: 'reflect_episodes', status: 'running' }
        : undefined
  )
  const displayedDreamingRunState = displayedDreamingRunStatus?.status
  const dreamingIsRunning = dreamingMutation.isPending || displayedDreamingRunState === 'running'
  const dreamingButtonLabel = dreamingIsRunning
    ? 'Dreaming run...'
    : displayedDreamingRunState === 'success'
      ? 'Dreaming Complete'
      : 'Dreaming'

  useEffect(() => {
    if (dreamingRunState && ['success', 'failed', 'dead_letter', 'crashed'].includes(dreamingRunState)) {
      void refetch()
    }
  }, [dreamingRunState, refetch])

  useEffect(() => {
    if (!dreamingRunIsTerminal) {
      setDreamingTerminalReady(false)
      return
    }
    const startedAt = dreamingStartedAt ?? Date.now()
    const remainingMs = Math.max(0, DREAMING_MIN_RUNNING_MS - (Date.now() - startedAt))
    if (remainingMs <= 0) {
      setDreamingTerminalReady(true)
      return
    }
    const timeoutId = window.setTimeout(() => {
      setDreamingTerminalReady(true)
    }, remainingMs)
    return () => window.clearTimeout(timeoutId)
  }, [dreamingRunId, dreamingRunIsTerminal, dreamingRunState, dreamingStartedAt])

  const memoryDocumentFocus = expandedProfileActivity || expandedEpisodeActivity || expandedAgentCaseActivity || expandedAgentSkillActivity || focusedActivity
  const {
    data: focusedDocument,
    isLoading: isDocumentLoading,
    error: documentError,
  } = useQuery({
    queryKey: ['everos-memory-document', memoryDocumentFocus?.md_path],
    queryFn: () => managedGet<EverOSMemoryDocument>(`/everos_memory/document?md_path=${encodeURIComponent(memoryDocumentFocus?.md_path || '')}`),
    enabled: !!memoryDocumentFocus?.md_path,
  })

  const filtered = useMemo(() => {
    const overview = data
    if (!overview) {
      return {
        profiles: [],
        episodes: [],
        agent_cases: [],
        agent_skills: [],
        recent_activity: [],
      }
    }

    return {
      profiles: overview.profiles.filter((item) =>
        includesQuery(searchQuery, [item.id, item.owner_id, item.summary, item.explicit_info_json, item.implicit_traits_json, item.md_path]),
      ),
      episodes: overview.episodes.filter((item) =>
        includesQuery(searchQuery, [item.id, item.entry_id, item.owner_id, item.session_id, item.subject, item.summary, item.episode, item.md_path]),
      ),
      agent_cases: overview.agent_cases.filter((item) =>
        includesQuery(searchQuery, [item.id, item.entry_id, item.owner_id, item.session_id, item.task_intent, item.approach, item.key_insight, item.md_path]),
      ),
      agent_skills: overview.agent_skills.filter((item) =>
        includesQuery(searchQuery, [item.id, item.owner_id, item.name, item.description, item.content, item.cluster_id, item.md_path]),
      ),
      recent_activity: overview.recent_activity
        .map((item) => {
          const details = activityDetails(item, overview)
          return {
            ...item,
            ...details,
            title: details.title || activityTitle(item, overview),
            source_label: formatSourceLabel(item.md_path),
          }
        })
        .filter((item) =>
          includesQuery(searchQuery, [
            item.id,
            item.entry_id,
            item.kind,
            item.owner_id,
            item.summary,
            item.subject,
            item.task_intent,
            item.name,
            item.title,
            item.md_path,
            item.source_label,
          ]),
        ),
    }
  }, [data, searchQuery])

  const allMemoryActivity = useMemo(() => buildMemoryActivityItems(filtered), [filtered])

  const filteredMemoryActivity = useMemo(() => {
    const hasKindFilter = selectedActivityKinds.length > 0
    return allMemoryActivity.filter((item) => (
      (!hasKindFilter || selectedActivityKinds.includes(item.kind))
      && isWithinTimeRange(getActivityTimestamp(item), activityTimeRange)
    ))
  }, [activityTimeRange, allMemoryActivity, selectedActivityKinds])

  const activityPageCount = Math.max(1, Math.ceil(filteredMemoryActivity.length / activityPageSize))
  const currentActivityPage = Math.min(activityPage, activityPageCount)
  const paginatedMemoryActivity = useMemo(() => {
    const start = (currentActivityPage - 1) * activityPageSize
    return filteredMemoryActivity.slice(start, start + activityPageSize)
  }, [activityPageSize, currentActivityPage, filteredMemoryActivity])

  const focusedProfiles = useMemo(
    () => filterFocusedMemory(filtered.profiles, focusedActivity, 'profile'),
    [filtered.profiles, focusedActivity],
  )
  const visibleProfiles = focusedActivity?.kind === 'episode' ? filtered.profiles : focusedProfiles
  const focusedEpisodes = useMemo(
    () => filterFocusedMemory(filtered.episodes, focusedActivity, 'episode'),
    [filtered.episodes, focusedActivity],
  )
  const visibleEpisodes = useMemo(() => {
    if (!episodeMetadataFilter) return focusedEpisodes
    return focusedEpisodes.filter((episode) => (
      episodeMetadataFilter.type === 'aggregated'
        ? episode.parent_type === 'cluster'
        : episodeMetadataFilter.type === 'user'
          ? episode.owner_id === episodeMetadataFilter.value
          : episode.session_id === episodeMetadataFilter.value
            || !!episode.source_session_ids?.includes(episodeMetadataFilter.value)
    ))
  }, [episodeMetadataFilter, focusedEpisodes])
  const focusedAgentCases = useMemo(
    () => filterFocusedMemory(filtered.agent_cases, focusedActivity, 'agent_case'),
    [filtered.agent_cases, focusedActivity],
  )
  const visibleAgentCases = useMemo(() => {
    const baseCases = expandedAgentCaseActivity ? filtered.agent_cases : focusedAgentCases
    if (!agentCaseMetadataFilter) return baseCases
    return baseCases.filter((item) => (
      agentCaseMetadataFilter.type === 'agent'
        ? item.owner_id === agentCaseMetadataFilter.value
        : item.session_id === agentCaseMetadataFilter.value
    ))
  }, [agentCaseMetadataFilter, expandedAgentCaseActivity, filtered.agent_cases, focusedAgentCases])
  const focusedAgentSkills = useMemo(
    () => filterFocusedMemory(filtered.agent_skills, focusedActivity, 'agent_skill'),
    [filtered.agent_skills, focusedActivity],
  )
  const visibleAgentSkills = useMemo(() => {
    const baseSkills = expandedAgentSkillActivity ? filtered.agent_skills : focusedAgentSkills
    if (!agentSkillMetadataFilter) return baseSkills
    return baseSkills.filter((item) => item.owner_id === agentSkillMetadataFilter.value)
  }, [agentSkillMetadataFilter, expandedAgentSkillActivity, filtered.agent_skills, focusedAgentSkills])

  const profilePageCount = Math.max(1, Math.ceil(visibleProfiles.length / profilePageSize))
  const currentProfilePage = Math.min(profilePage, profilePageCount)
  const paginatedProfiles = useMemo(() => {
    const start = (currentProfilePage - 1) * profilePageSize
    return visibleProfiles.slice(start, start + profilePageSize)
  }, [currentProfilePage, profilePageSize, visibleProfiles])

  const episodePageCount = Math.max(1, Math.ceil(visibleEpisodes.length / episodePageSize))
  const currentEpisodePage = Math.min(episodePage, episodePageCount)
  const paginatedEpisodes = useMemo(() => {
    const start = (currentEpisodePage - 1) * episodePageSize
    return visibleEpisodes.slice(start, start + episodePageSize)
  }, [currentEpisodePage, episodePageSize, visibleEpisodes])

  const agentCasePageCount = Math.max(1, Math.ceil(visibleAgentCases.length / agentCasePageSize))
  const currentAgentCasePage = Math.min(agentCasePage, agentCasePageCount)
  const paginatedAgentCases = useMemo(() => {
    const start = (currentAgentCasePage - 1) * agentCasePageSize
    return visibleAgentCases.slice(start, start + agentCasePageSize)
  }, [agentCasePageSize, currentAgentCasePage, visibleAgentCases])

  const agentSkillPageCount = Math.max(1, Math.ceil(visibleAgentSkills.length / agentSkillPageSize))
  const currentAgentSkillPage = Math.min(agentSkillPage, agentSkillPageCount)
  const paginatedAgentSkills = useMemo(() => {
    const start = (currentAgentSkillPage - 1) * agentSkillPageSize
    return visibleAgentSkills.slice(start, start + agentSkillPageSize)
  }, [agentSkillPageSize, currentAgentSkillPage, visibleAgentSkills])

  const resetPanelPages = () => {
    setProfilePage(1)
    setEpisodePage(1)
    setAgentCasePage(1)
    setAgentSkillPage(1)
  }

  const handleTabChange = (value: string) => {
    setTab(value)
    setFocusedActivity(null)
    setExpandedProfileActivity(null)
    setExpandedEpisodeActivity(null)
    setExpandedAgentCaseActivity(null)
    setExpandedAgentSkillActivity(null)
    setLockedDetailKind(null)
    setEpisodeMetadataFilter(null)
    setAgentCaseMetadataFilter(null)
    setAgentSkillMetadataFilter(null)
    resetPanelPages()
    if (value === 'overview') {
      setActivityFilter('all')
      setSelectedActivityKinds([])
      setActivityTimeRange('all')
      setActivityPage(1)
    }
  }

  const handleActivityFilterChange = (filter: Exclude<ActivityFilter, 'all'>) => {
    const isOnlySelectedFilter = selectedActivityKinds.length === 1 && selectedActivityKinds[0] === filter
    setTab('overview')
    setFocusedActivity(null)
    setExpandedProfileActivity(null)
    setExpandedEpisodeActivity(null)
    setExpandedAgentCaseActivity(null)
    setExpandedAgentSkillActivity(null)
    setLockedDetailKind(null)
    setActivityFilter(isOnlySelectedFilter ? 'all' : filter)
    setSelectedActivityKinds(isOnlySelectedFilter ? [] : [filter])
    setActivityTimeRange('all')
    setActivityPage(1)
  }

  const handleActivityPageSizeChange = (pageSize: number) => {
    setActivityPageSize(pageSize)
    setActivityPage(1)
  }

  const handleProfilePageSizeChange = (pageSize: number) => {
    setProfilePageSize(pageSize)
    setProfilePage(1)
  }

  const handleEpisodePageSizeChange = (pageSize: number) => {
    setEpisodePageSize(pageSize)
    setEpisodePage(1)
  }

  const handleAgentCasePageSizeChange = (pageSize: number) => {
    setAgentCasePageSize(pageSize)
    setAgentCasePage(1)
  }

  const handleAgentSkillPageSizeChange = (pageSize: number) => {
    setAgentSkillPageSize(pageSize)
    setAgentSkillPage(1)
  }

  const handleOverviewClick = () => {
    setActivityFilter('all')
    setSelectedActivityKinds([])
    setActivityTimeRange('all')
    setActivityPage(1)
    setFocusedActivity(null)
    setExpandedProfileActivity(null)
    setExpandedEpisodeActivity(null)
    setExpandedAgentCaseActivity(null)
    setExpandedAgentSkillActivity(null)
    setLockedDetailKind(null)
    setEpisodeMetadataFilter(null)
    setAgentCaseMetadataFilter(null)
    setAgentSkillMetadataFilter(null)
    resetPanelPages()
  }

  const toggleActivityKind = (kind: ActivityKindFilter) => {
    setTab('overview')
    setFocusedActivity(null)
    setExpandedProfileActivity(null)
    setExpandedEpisodeActivity(null)
    setExpandedAgentCaseActivity(null)
    setExpandedAgentSkillActivity(null)
    setLockedDetailKind(null)
    setActivityPage(1)
    setSelectedActivityKinds((current) => {
      const next = current.includes(kind)
        ? current.filter((item) => item !== kind)
        : [...current, kind]
      setActivityFilter(next.length === 1 ? next[0] : 'all')
      return next
    })
  }

  const handleActivityTimeRangeChange = (value: ActivityTimeRange) => {
    setActivityTimeRange(value)
    setActivityPage(1)
  }

  const handleActivityDetail = (item: RecentActivity) => {
    if (item.kind === 'profile') {
      setFocusedActivity(null)
      setExpandedProfileActivity(item)
      setExpandedEpisodeActivity(null)
      setExpandedAgentCaseActivity(null)
      setExpandedAgentSkillActivity(null)
      setLockedDetailKind('profile')
      setEpisodeMetadataFilter(item.owner_id ? { type: 'user', value: item.owner_id } : null)
      setAgentCaseMetadataFilter(null)
      setAgentSkillMetadataFilter(null)
      setTab('users')
      setActivityFilter('all')
      setSelectedActivityKinds([])
      setActivityTimeRange('all')
      setActivityPage(1)
      return
    }

    if (item.kind === 'episode') {
      setFocusedActivity(null)
      setExpandedProfileActivity(null)
      setExpandedEpisodeActivity(item)
      setExpandedAgentCaseActivity(null)
      setExpandedAgentSkillActivity(null)
      setLockedDetailKind('episode')
      setEpisodeMetadataFilter(null)
      setAgentCaseMetadataFilter(null)
      setAgentSkillMetadataFilter(null)
      setTab('users')
      setActivityFilter('all')
      setSelectedActivityKinds([])
      setActivityTimeRange('all')
      setActivityPage(1)
      return
    }

    if (item.kind === 'agent_case') {
      setFocusedActivity(null)
      setExpandedProfileActivity(null)
      setExpandedEpisodeActivity(null)
      setExpandedAgentCaseActivity(item)
      setExpandedAgentSkillActivity(null)
      setLockedDetailKind('agent_case')
      setEpisodeMetadataFilter(null)
      setAgentCaseMetadataFilter(null)
      setAgentSkillMetadataFilter(null)
      setTab('agents')
      setActivityFilter('all')
      setSelectedActivityKinds([])
      setActivityTimeRange('all')
      setActivityPage(1)
      return
    }

    if (item.kind === 'agent_skill') {
      setFocusedActivity(null)
      setExpandedProfileActivity(null)
      setExpandedEpisodeActivity(null)
      setExpandedAgentCaseActivity(null)
      setExpandedAgentSkillActivity(item)
      setLockedDetailKind('agent_skill')
      setEpisodeMetadataFilter(null)
      setAgentCaseMetadataFilter(null)
      setAgentSkillMetadataFilter(null)
      setTab('agents')
      setActivityFilter('all')
      setSelectedActivityKinds([])
      setActivityTimeRange('all')
      setActivityPage(1)
      return
    }

    setFocusedActivity(item)
    setExpandedProfileActivity(null)
    setExpandedEpisodeActivity(null)
    setExpandedAgentCaseActivity(null)
    setExpandedAgentSkillActivity(null)
    setLockedDetailKind(null)
    setEpisodeMetadataFilter(null)
    setAgentCaseMetadataFilter(null)
    setAgentSkillMetadataFilter(null)
    setTab(detailTabForKind(item.kind))
    setActivityFilter('all')
    setSelectedActivityKinds([])
    setActivityTimeRange('all')
    setActivityPage(1)
  }

  const handleEpisodeDetail = (episode: EpisodeMemory) => {
    setFocusedActivity(null)
    setExpandedProfileActivity(null)
    setExpandedEpisodeActivity(episodeToActivity(episode))
    setExpandedAgentCaseActivity(null)
    setExpandedAgentSkillActivity(null)
    setLockedDetailKind(null)
    setTab('users')
  }

  const handleProfileSelect = (profile: UserProfileMemory) => {
    setFocusedActivity(null)
    setExpandedEpisodeActivity(null)
    setExpandedAgentCaseActivity(null)
    setExpandedAgentSkillActivity(null)
    setLockedDetailKind(null)
    setEpisodeMetadataFilter((current) => (
      current?.type === 'user' && current.value === profile.owner_id
        ? null
        : { type: 'user', value: profile.owner_id }
    ))
    setAgentCaseMetadataFilter(null)
    setAgentSkillMetadataFilter(null)
    setEpisodePage(1)
    setTab('users')
  }

  const handleProfileDetail = (profile: UserProfileMemory) => {
    setFocusedActivity(null)
    setExpandedProfileActivity(profileToActivity(profile))
    setExpandedEpisodeActivity(null)
    setExpandedAgentCaseActivity(null)
    setExpandedAgentSkillActivity(null)
    setLockedDetailKind(null)
    setProfilePage(1)
    setTab('users')
  }

  const handleAgentCaseDetail = (item: AgentCaseMemory) => {
    setFocusedActivity(null)
    setExpandedProfileActivity(null)
    setExpandedEpisodeActivity(null)
    setExpandedAgentCaseActivity(agentCaseToActivity(item))
    setExpandedAgentSkillActivity(null)
    setLockedDetailKind(null)
    setTab('agents')
  }

  const handleAgentSkillSelect = (item: AgentSkillMemory) => {
    setFocusedActivity(null)
    setExpandedProfileActivity(null)
    setExpandedEpisodeActivity(null)
    setExpandedAgentCaseActivity(null)
    setLockedDetailKind(null)
    setEpisodeMetadataFilter(null)
    setAgentCaseMetadataFilter((current) => (
      current?.type === 'agent' && current.value === item.owner_id
        ? null
        : { type: 'agent', value: item.owner_id }
    ))
    setAgentCasePage(1)
    setTab('agents')
  }

  const handleAgentSkillDetail = (item: AgentSkillMemory) => {
    setFocusedActivity(null)
    setExpandedProfileActivity(null)
    setExpandedEpisodeActivity(null)
    setExpandedAgentCaseActivity(null)
    setExpandedAgentSkillActivity(agentSkillToActivity(item))
    setLockedDetailKind(null)
    setAgentSkillPage(1)
    setTab('agents')
  }

  const handleEpisodeMetadataFilter = (filter: Exclude<EpisodeMetadataFilter, null>) => {
    setFocusedActivity(null)
    setExpandedProfileActivity(null)
    setExpandedEpisodeActivity(null)
    setExpandedAgentCaseActivity(null)
    setExpandedAgentSkillActivity(null)
    setLockedDetailKind(null)
    setEpisodeMetadataFilter(filter)
    setEpisodePage(1)
  }

  const handleAgentCaseMetadataFilter = (filter: Exclude<AgentCaseMetadataFilter, null>) => {
    setFocusedActivity(null)
    setExpandedProfileActivity(null)
    setExpandedEpisodeActivity(null)
    setExpandedAgentCaseActivity(null)
    setExpandedAgentSkillActivity(null)
    setLockedDetailKind(null)
    setAgentCaseMetadataFilter(filter)
    setAgentCasePage(1)
  }

  const handleAgentSkillMetadataFilter = (filter: Exclude<AgentSkillMetadataFilter, null>) => {
    setFocusedActivity(null)
    setExpandedProfileActivity(null)
    setExpandedEpisodeActivity(null)
    setExpandedAgentCaseActivity(null)
    setExpandedAgentSkillActivity(null)
    setLockedDetailKind(null)
    setAgentSkillMetadataFilter(filter)
    setAgentSkillPage(1)
  }

  if (isError) {
    return <ResourceErrorState error={error} resource="memoryStore" onRetry={() => refetch()} />
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="记忆存储"
        subtitle="查看自动沉淀的用户记忆与智能体记忆。"
        action={
          <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={cn('h-4 w-4', isFetching && 'animate-spin')} />
            刷新
          </Button>
        }
      />

      <div className="flex flex-col gap-3 rounded-md border bg-card p-3 md:flex-row md:items-center md:justify-between">
        <Tabs value={tab} onValueChange={handleTabChange}>
          <TabsList>
            <TabsTrigger value="overview" onClick={handleOverviewClick}>总览</TabsTrigger>
            <TabsTrigger value="users">用户记忆</TabsTrigger>
            <TabsTrigger value="agents">智能体记忆</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="relative w-full md:max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(event) => {
              setSearchQuery(event.target.value)
              setActivityPage(1)
              resetPanelPages()
            }}
            placeholder="搜索记忆内容、路径、会话或智能体"
            className="pl-9"
          />
        </div>
      </div>

      {isLoading || !data ? (
        <LoadingState />
      ) : (
        <>
          <Tabs value={tab} onValueChange={handleTabChange}>
            <TabsContent value="overview" className="mt-0 space-y-4">
              <div className="grid gap-3 md:grid-cols-4">
                <MetricCard
                  label={activityFilters[0].label}
                  value={data.counts[activityFilters[0].countKey]}
                  description={activityFilters[0].description}
                  icon={activityFilters[0].icon}
                  className={activityFilters[0].className}
                  active={activityFilter === activityFilters[0].filter}
                  onClick={() => handleActivityFilterChange(activityFilters[0].filter)}
                />
                <MetricCard
                  label={activityFilters[1].label}
                  value={data.counts[activityFilters[1].countKey]}
                  description={activityFilters[1].description}
                  icon={activityFilters[1].icon}
                  className={activityFilters[1].className}
                  active={activityFilter === activityFilters[1].filter}
                  onClick={() => handleActivityFilterChange(activityFilters[1].filter)}
                />
                <MetricCard
                  label={activityFilters[2].label}
                  value={data.counts[activityFilters[2].countKey]}
                  description={activityFilters[2].description}
                  icon={activityFilters[2].icon}
                  className={activityFilters[2].className}
                  active={activityFilter === activityFilters[2].filter}
                  onClick={() => handleActivityFilterChange(activityFilters[2].filter)}
                />
                <MetricCard
                  label={activityFilters[3].label}
                  value={data.counts[activityFilters[3].countKey]}
                  description={activityFilters[3].description}
                  icon={activityFilters[3].icon}
                  className={activityFilters[3].className}
                  active={activityFilter === activityFilters[3].filter}
                  onClick={() => handleActivityFilterChange(activityFilters[3].filter)}
                />
              </div>
              <div data-testid="recent-memory-activity">
                <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-2">
                    <Activity className="h-4 w-4" />
                    <span className="text-sm font-semibold text-foreground">全部记忆</span>
                    {activityFilter !== 'all' ? (
                      <Badge variant="outline">{activityFilterLabels[activityFilter]}</Badge>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <ActivityTypeFilter selectedKinds={selectedActivityKinds} onToggle={toggleActivityKind} />
                    <ActivityTimeFilter value={activityTimeRange} onChange={handleActivityTimeRangeChange} />
                  </div>
                </div>
                <ActivityList
                  items={paginatedMemoryActivity}
                  onOpenDetail={handleActivityDetail}
                  emptyTitle={
                    selectedActivityKinds.length === 0
                      ? '暂无记忆内容'
                      : `暂无 ${selectedActivityKinds.map((kind) => activityFilterLabels[kind]).join(' / ')} 记忆`
                  }
                  emptyDescription={
                    activityFilter === 'all'
                      ? '写入记忆后会在这里显示完整列表。'
                      : '当前筛选条件下没有匹配的记忆内容。'
                  }
                />
                <ActivityPagination
                  page={currentActivityPage}
                  pageCount={activityPageCount}
                  pageSize={activityPageSize}
                  pageSizeOptions={ACTIVITY_PAGE_SIZE_OPTIONS}
                  onPageChange={setActivityPage}
                  onPageSizeChange={handleActivityPageSizeChange}
                />
              </div>
            </TabsContent>

            <TabsContent value="users" className="mt-0">
              <div className="grid gap-4 xl:grid-cols-[minmax(280px,420px)_1fr]">
                <section data-testid="profile-memory-section" className="space-y-3">
                  <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <UserRound className="h-4 w-4" />
                    Profiles
                  </div>
                  {visibleProfiles.length ? (
                    <>
                      <div className="space-y-3">
                        {paginatedProfiles.map((profile) => (
                          <ProfileCard
                            key={profile.id}
                            profile={profile}
                            focusedActivity={expandedProfileActivity || (focusedActivity?.kind === 'profile' ? focusedActivity : null)}
                            selected={episodeMetadataFilter?.type === 'user' && episodeMetadataFilter.value === profile.owner_id}
                            document={focusedDocument}
                            loading={isDocumentLoading}
                            error={documentError}
                            onClear={() => {
                              setFocusedActivity(null)
                              setExpandedProfileActivity(null)
                              setLockedDetailKind(null)
                            }}
                            onSelect={handleProfileSelect}
                            onOpenDetail={handleProfileDetail}
                          />
                        ))}
                      </div>
                      <ActivityPagination
                        page={currentProfilePage}
                        pageCount={profilePageCount}
                        pageSize={profilePageSize}
                        pageSizeOptions={ACTIVITY_PAGE_SIZE_OPTIONS}
                        onPageChange={setProfilePage}
                        onPageSizeChange={handleProfilePageSizeChange}
                      />
                    </>
                  ) : (
                    <EmptyState title="暂无用户画像" description="提取用户画像后会展示显式信息和隐式特征。" />
                  )}
                </section>
                <section data-testid="episode-memory-section" className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                      <BookOpenText className="h-4 w-4" />
                      Episodes
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <EpisodeMetadataFilterChip
                        filter={episodeMetadataFilter}
                        onClear={() => setEpisodeMetadataFilter(null)}
                      />
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        aria-label="Start Dreaming for Episodes"
                        onClick={() => dreamingMutation.mutate()}
                        disabled={dreamingIsRunning}
                        className="min-w-[180px]"
                      >
                        <Sparkles className={cn('h-4 w-4', dreamingIsRunning && 'animate-pulse')} />
                        {dreamingButtonLabel}
                      </Button>
                    </div>
                  </div>
                  <EpisodeTimeline
                    episodes={paginatedEpisodes}
                    atomicFacts={data?.atomic_facts ?? []}
                    focusedActivity={expandedEpisodeActivity || (focusedActivity?.kind === 'episode' ? focusedActivity : null)}
                    document={focusedDocument}
                    loading={isDocumentLoading}
                    error={documentError}
                    autoScrollFocused={lockedDetailKind === 'episode'}
                    disableUnfocusedExpand={lockedDetailKind === 'episode'}
                    onClear={() => {
                      setFocusedActivity(null)
                      setExpandedProfileActivity(null)
                      setExpandedEpisodeActivity(null)
                      setLockedDetailKind(null)
                    }}
                    onOpenDetail={handleEpisodeDetail}
                    onFilter={handleEpisodeMetadataFilter}
                  />
                  {visibleEpisodes.length ? (
                    <ActivityPagination
                      page={currentEpisodePage}
                      pageCount={episodePageCount}
                      pageSize={episodePageSize}
                      pageSizeOptions={ACTIVITY_PAGE_SIZE_OPTIONS}
                      onPageChange={setEpisodePage}
                      onPageSizeChange={handleEpisodePageSizeChange}
                    />
                  ) : null}
                </section>
              </div>
            </TabsContent>

            <TabsContent value="agents" className="mt-0">
              <div className="grid gap-4 xl:grid-cols-2">
                <section data-testid="agent-case-section" className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                      <GitBranch className="h-4 w-4" />
                      Agent Cases
                    </div>
                    <AgentCaseMetadataFilterChip
                      filter={agentCaseMetadataFilter}
                      onClear={() => setAgentCaseMetadataFilter(null)}
                    />
                  </div>
                  <AgentCaseTimeline
                    cases={paginatedAgentCases}
                    focusedActivity={expandedAgentCaseActivity || (focusedActivity?.kind === 'agent_case' ? focusedActivity : null)}
                    document={focusedDocument}
                    loading={isDocumentLoading}
                    error={documentError}
                    autoScrollFocused={lockedDetailKind === 'agent_case'}
                    disableUnfocusedExpand={lockedDetailKind === 'agent_case'}
                    onClear={() => {
                      setFocusedActivity(null)
                      setExpandedProfileActivity(null)
                      setExpandedAgentCaseActivity(null)
                      setLockedDetailKind(null)
                    }}
                    onOpenDetail={handleAgentCaseDetail}
                    onFilter={handleAgentCaseMetadataFilter}
                  />
                  {visibleAgentCases.length ? (
                    <ActivityPagination
                      page={currentAgentCasePage}
                      pageCount={agentCasePageCount}
                      pageSize={agentCasePageSize}
                      pageSizeOptions={ACTIVITY_PAGE_SIZE_OPTIONS}
                      onPageChange={setAgentCasePage}
                      onPageSizeChange={handleAgentCasePageSizeChange}
                    />
                  ) : null}
                </section>
                <section data-testid="agent-skill-section" className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                      <Wrench className="h-4 w-4" />
                      Agent Skills
                    </div>
                    <AgentSkillMetadataFilterChip
                      filter={agentSkillMetadataFilter}
                      onClear={() => setAgentSkillMetadataFilter(null)}
                    />
                  </div>
                  {visibleAgentSkills.length ? (
                    <>
                      <div data-testid="agent-skill-list" className="space-y-3">
                        {paginatedAgentSkills.map((item) => (
                          <AgentSkillCard
                            key={item.id}
                            item={item}
                            focusedActivity={expandedAgentSkillActivity || (focusedActivity?.kind === 'agent_skill' ? focusedActivity : null)}
                            selected={agentCaseMetadataFilter?.type === 'agent' && agentCaseMetadataFilter.value === item.owner_id}
                            document={focusedDocument}
                            loading={isDocumentLoading}
                            error={documentError}
                            onClear={() => {
                              setFocusedActivity(null)
                              setExpandedProfileActivity(null)
                              setExpandedAgentSkillActivity(null)
                              setLockedDetailKind(null)
                            }}
                            onSelect={handleAgentSkillSelect}
                            onOpenDetail={handleAgentSkillDetail}
                            onFilter={handleAgentSkillMetadataFilter}
                          />
                        ))}
                      </div>
                      <ActivityPagination
                        page={currentAgentSkillPage}
                        pageCount={agentSkillPageCount}
                        pageSize={agentSkillPageSize}
                        pageSizeOptions={ACTIVITY_PAGE_SIZE_OPTIONS}
                        onPageChange={setAgentSkillPage}
                        onPageSizeChange={handleAgentSkillPageSizeChange}
                      />
                    </>
                  ) : (
                    <EmptyState title="暂无 Agent Skill" description="从高质量案例归纳技能后会展示在这里。" />
                  )}
                </section>
              </div>
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  )
}
