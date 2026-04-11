'use client'

/**
 * ExecutionTreeNodeContent - Renders the content of a single tree node.
 *
 * Responsibilities:
 * - Display node icon, name, duration, status badge
 * - Color coding by node type
 * - Decoupled from tree structure (indentation, lines handled by parent)
 *
 * Inspired by langfuse SpanContent.tsx
 */

import {
  Box,
  BrainCircuit,
  Cpu,
  Wrench,
  Terminal,
  Zap,
  Code2,
  Eye,
  CheckSquare,
  ListTodo,
  AlertTriangle,
  Clock,
} from 'lucide-react'

import { cn } from '@/lib/utils'
import type { ExecutionTreeNode } from '@/types'

interface ExecutionTreeNodeContentProps {
  node: ExecutionTreeNode
  isSelected: boolean
  onClick: () => void
}

function getNodeIcon(node: ExecutionTreeNode) {
  if (node.status === 'running') {
    return <Zap size={13} className="animate-pulse fill-[color-mix(in_srgb,var(--brand-secondary)_10%,transparent)] text-[var(--brand-secondary)]" />
  }

  const stepType = node.step?.stepType
  switch (stepType) {
    case 'node_lifecycle':
      return (
        <Cpu
          size={13}
          className={node.status === 'success' ? 'text-[var(--status-success)]' : 'text-[var(--brand-500)]'}
        />
      )
    case 'agent_thought':
      return <BrainCircuit size={13} className="text-[var(--brand-500)]" />
    case 'tool_execution':
      return <Wrench size={13} className="text-[var(--status-warning)]" />
    case 'model_io':
      return <Box size={13} className="text-[var(--brand-500)]" />
    case 'code_agent_thought':
      return <BrainCircuit size={13} className="text-[var(--brand-600)]" />
    case 'code_agent_code':
      return <Code2 size={13} className="text-[var(--brand-500)]" />
    case 'code_agent_observation':
      return <Eye size={13} className="text-[var(--brand-tertiary)]" />
    case 'code_agent_final_answer':
      return <CheckSquare size={13} className="text-[var(--status-success)]" />
    case 'code_agent_planning':
      return <ListTodo size={13} className="text-[var(--status-warning)]" />
    case 'code_agent_error':
      return <AlertTriangle size={13} className="text-[var(--status-error)]" />
    default:
      return <Terminal size={13} className="text-[var(--text-tertiary)]" />
  }
}

function getStatusDot(status: string) {
  switch (status) {
    case 'running':
      return <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-[var(--brand-secondary)]" />
    case 'success':
      return <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--status-success)]" />
    case 'error':
      return <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--status-error)]" />
    case 'waiting':
      return <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-[var(--status-warning)]" />
    default:
      return <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--text-subtle)]" />
  }
}

function formatDuration(ms: number | undefined): string {
  if (ms === undefined || ms === null) return ''
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
}

export function ExecutionTreeNodeContent({
  node,
  isSelected,
  onClick,
}: ExecutionTreeNodeContentProps) {
  const isParentNode = node.type === 'NODE' || node.type === 'TRACE'
  const duration = node.duration || (node.endTime ? node.endTime - node.startTime : undefined)

  return (
    <div
      onClick={onClick}
      className={cn(
        'group flex min-w-0 cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 transition-all duration-150',
        isSelected ? 'bg-primary/5 ring-1 ring-primary/20' : 'hover:bg-[var(--surface-2)]',
      )}
    >
      {/* Icon */}
      <div
        className={cn(
          'flex h-5 w-5 shrink-0 items-center justify-center rounded',
          isParentNode ? 'border border-[var(--border)] bg-[var(--surface-3)]' : 'border border-[var(--border-muted)] bg-[var(--surface-elevated)]',
        )}
      >
        {getNodeIcon(node)}
      </div>

      {/* Name */}
      <span
        className={cn(
          'min-w-0 flex-1 truncate text-sm font-medium',
          isParentNode ? 'font-semibold text-[var(--text-primary)]' : 'text-[var(--text-secondary)]',
          isSelected && 'text-primary',
        )}
      >
        {node.name}
      </span>

      {/* Right side: duration + status */}
      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        {duration !== undefined && duration > 0 && (
          <span className="flex items-center gap-0.5 font-mono text-xs text-[var(--text-muted)]">
            <Clock size={8} className="opacity-60" />
            {formatDuration(duration)}
          </span>
        )}
        {getStatusDot(node.status)}
      </div>
    </div>
  )
}
