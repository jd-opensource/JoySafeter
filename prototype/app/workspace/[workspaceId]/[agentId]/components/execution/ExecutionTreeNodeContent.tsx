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
import React from 'react'

import { cn } from '@/lib/core/utils/cn'
import type { ExecutionTreeNode } from '@/types'

interface ExecutionTreeNodeContentProps {
  node: ExecutionTreeNode
  isSelected: boolean
  onClick: () => void
}

function getNodeIcon(node: ExecutionTreeNode) {
  if (node.status === 'running') {
    return <Zap size={13} className="text-cyan-600 fill-cyan-100 animate-pulse" />
  }

  const stepType = node.step?.stepType
  switch (stepType) {
    case 'node_lifecycle':
      return <Cpu size={13} className={node.status === 'success' ? 'text-emerald-500' : 'text-blue-500'} />
    case 'agent_thought':
      return <BrainCircuit size={13} className="text-purple-500" />
    case 'tool_execution':
      return <Wrench size={13} className="text-amber-500" />
    case 'model_io':
      return <Box size={13} className="text-blue-500" />
    case 'code_agent_thought':
      return <BrainCircuit size={13} className="text-indigo-500" />
    case 'code_agent_code':
      return <Code2 size={13} className="text-blue-600" />
    case 'code_agent_observation':
      return <Eye size={13} className="text-teal-500" />
    case 'code_agent_final_answer':
      return <CheckSquare size={13} className="text-green-600" />
    case 'code_agent_planning':
      return <ListTodo size={13} className="text-orange-500" />
    case 'code_agent_error':
      return <AlertTriangle size={13} className="text-red-500" />
    default:
      return <Terminal size={13} className="text-gray-500" />
  }
}

function getStatusDot(status: string) {
  switch (status) {
    case 'running':
      return <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse shrink-0" />
    case 'success':
      return <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" />
    case 'error':
      return <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" />
    case 'waiting':
      return <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse shrink-0" />
    default:
      return <span className="w-1.5 h-1.5 rounded-full bg-gray-300 shrink-0" />
  }
}

function formatDuration(ms: number | undefined): string {
  if (ms === undefined || ms === null) return ''
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
}

export const ExecutionTreeNodeContent: React.FC<ExecutionTreeNodeContentProps> = ({
  node,
  isSelected,
  onClick,
}) => {
  const isParentNode = node.type === 'NODE' || node.type === 'TRACE'
  const duration = node.duration || (node.endTime ? node.endTime - node.startTime : undefined)

  return (
    <div
      onClick={onClick}
      className={cn(
        'flex items-center gap-2 py-1.5 px-2 cursor-pointer transition-all duration-150 rounded-sm group min-w-0',
        isSelected
          ? 'bg-blue-50 ring-1 ring-blue-200'
          : 'hover:bg-gray-50',
      )}
    >
      {/* Icon */}
      <div
        className={cn(
          'w-5 h-5 rounded flex items-center justify-center shrink-0',
          isParentNode
            ? 'bg-gray-100 border border-gray-200'
            : 'bg-white border border-gray-150',
        )}
      >
        {getNodeIcon(node)}
      </div>

      {/* Name */}
      <span
        className={cn(
          'text-[11px] font-medium truncate flex-1 min-w-0',
          isParentNode ? 'font-semibold text-gray-800' : 'text-gray-600',
          isSelected && 'text-blue-800',
        )}
      >
        {node.name}
      </span>

      {/* Right side: duration + status */}
      <div className="flex items-center gap-1.5 shrink-0 ml-auto">
        {duration !== undefined && duration > 0 && (
          <span className="text-[9px] text-gray-400 font-mono flex items-center gap-0.5">
            <Clock size={8} className="opacity-60" />
            {formatDuration(duration)}
          </span>
        )}
        {getStatusDot(node.status)}
      </div>
    </div>
  )
}
