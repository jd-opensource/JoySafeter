'use client'

import { ArrowDown, ArrowUp, Calendar, ExternalLink } from 'lucide-react'
import Link from 'next/link'
import { useMemo, useState } from 'react'

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import { PulsingDot } from '@/components/ui/pulsing-dot'
import type { Task, TaskStatus } from '@/types/missions'
import {
  TASK_PRIORITY_LABELS,
  TASK_STATUS_LABELS,
  TASK_STATUS_ORDER,
  TASK_STATUS_STYLES,
} from '@/types/missions'

import { PriorityBadge } from './priority-badge'

type SortField = 'title' | 'status' | 'priority' | 'updated_at' | 'due_date'

interface TaskListViewProps {
  tasks: Task[]
  agentsMap: Record<string, string>
  onSelectTask?: (id: string) => void
}

const PRIORITY_ORDER: Record<string, number> = Object.fromEntries(
  Object.keys(TASK_PRIORITY_LABELS)
    .reverse()
    .map((k, i) => [k, i]),
)
const STATUS_ORDER: Record<string, number> = Object.fromEntries(
  TASK_STATUS_ORDER.map((s, i) => [s, i]),
)

export function TaskListView({ tasks, agentsMap, onSelectTask }: TaskListViewProps) {
  const { t } = useTranslation()
  const [sortField, setSortField] = useState<SortField>('updated_at')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortDir('asc')
    }
  }

  const sorted = useMemo(() => {
    const arr = [...tasks]
    const dir = sortDir === 'asc' ? 1 : -1

    arr.sort((a, b) => {
      switch (sortField) {
        case 'title':
          return dir * a.title.localeCompare(b.title)
        case 'status':
          return dir * ((STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9))
        case 'priority':
          return dir * ((PRIORITY_ORDER[a.priority] ?? 9) - (PRIORITY_ORDER[b.priority] ?? 9))
        case 'due_date': {
          const da = a.due_date ? new Date(a.due_date).getTime() : Infinity
          const db = b.due_date ? new Date(b.due_date).getTime() : Infinity
          return dir * (da - db)
        }
        case 'updated_at':
          return dir * (new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime())
        default:
          return 0
      }
    })
    return arr
  }, [tasks, sortField, sortDir])

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return null
    return sortDir === 'asc' ? (
      <ArrowUp className="ml-1 inline h-3 w-3" />
    ) : (
      <ArrowDown className="ml-1 inline h-3 w-3" />
    )
  }

  return (
    <div className="overflow-auto p-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[40%] cursor-pointer" onClick={() => toggleSort('title')}>
              Title <SortIcon field="title" />
            </TableHead>
            <TableHead className="cursor-pointer" onClick={() => toggleSort('status')}>
              Status <SortIcon field="status" />
            </TableHead>
            <TableHead className="cursor-pointer" onClick={() => toggleSort('priority')}>
              Priority <SortIcon field="priority" />
            </TableHead>
            <TableHead>Agent</TableHead>
            <TableHead>Tags</TableHead>
            <TableHead className="cursor-pointer" onClick={() => toggleSort('due_date')}>
              Due <SortIcon field="due_date" />
            </TableHead>
            <TableHead
              className="cursor-pointer text-right"
              onClick={() => toggleSort('updated_at')}
            >
              Updated <SortIcon field="updated_at" />
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((m) => {
            const isOverdue = m.due_date ? Date.parse(m.due_date) < Date.now() : false
            return (
              <TableRow
                key={m.id}
                className="cursor-pointer hover:bg-[var(--surface-2)]"
                onClick={() => onSelectTask?.(m.id)}
              >
                <TableCell className="font-medium">{m.title}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        'inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium',
                        TASK_STATUS_STYLES[m.status] ??
                          'bg-[var(--surface-3)] text-[var(--text-muted)]',
                      )}
                    >
                      {TASK_STATUS_LABELS[m.status]}
                    </span>
                    {m.current_execution_id && (
                      <Link
                        href={`/runs?tab=executions&task=${m.id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="inline-flex items-center gap-1 text-[10px] text-[var(--status-success)] hover:underline"
                      >
                        <PulsingDot size="sm" />
                        {t('tasks.running')}
                      </Link>
                    )}
                    {/* Show last run link when there's a linked run but no active execution */}
                    {m.latest_run_id && !m.current_execution_id && (
                      <Link
                        href={`/runs?task=${m.id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="inline-flex items-center gap-1 text-[10px] text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:underline"
                      >
                        <ExternalLink className="h-2.5 w-2.5" />
                        {t('tasks.lastRun')}
                      </Link>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  <PriorityBadge priority={m.priority} />
                </TableCell>
                <TableCell className="text-xs text-[var(--text-muted)]">
                  {/* Support both new agent_id and legacy assignee_id */}
                  {(m.agent_id ?? m.assignee_id)
                    ? (agentsMap[m.agent_id ?? m.assignee_id ?? ''] ?? 'Agent')
                    : '—'}
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {m.tags?.slice(0, 2).map((t) => (
                      <span
                        key={t}
                        className="inline-block max-w-[60px] truncate rounded bg-[var(--surface-3)] px-1 py-0.5 text-[10px] text-[var(--text-secondary)]"
                      >
                        {t}
                      </span>
                    ))}
                    {(m.tags?.length ?? 0) > 2 && (
                      <span className="text-[10px] text-[var(--text-muted)]">
                        +{(m.tags?.length ?? 0) - 2}
                      </span>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  {m.due_date ? (
                    <span
                      className={cn(
                        'inline-flex items-center gap-1 text-xs',
                        isOverdue ? 'text-[var(--status-error)]' : 'text-[var(--text-muted)]',
                      )}
                    >
                      <Calendar className="h-3 w-3" />
                      {new Date(m.due_date).toLocaleDateString()}
                    </span>
                  ) : (
                    <span className="text-xs text-[var(--text-muted)]">—</span>
                  )}
                </TableCell>
                <TableCell className="text-right text-xs text-[var(--text-muted)]">
                  {new Date(m.updated_at).toLocaleDateString()}
                </TableCell>
              </TableRow>
            )
          })}
          {sorted.length === 0 && (
            <TableRow>
              <TableCell colSpan={7} className="py-8 text-center text-sm text-[var(--text-muted)]">
                No tasks yet
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  )
}
