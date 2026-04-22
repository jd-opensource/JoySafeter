'use client'

import { Badge } from '@/components/ui/badge'
import type { ToolCall } from '@/types/chat'

interface ToolCallBadgeProps {
  name: string
  args?: Record<string, unknown>
  status?: 'running' | 'completed' | 'failed'
}

export function ToolCallBadge({ name, status }: ToolCallBadgeProps) {
  return (
    <Badge
      variant="outline"
      className={`text-xs ${status === 'running' ? 'animate-pulse' : ''} ${status === 'failed' ? 'border-red-400 text-red-500' : ''}`}
    >
      {name}
    </Badge>
  )
}

export function formatToolDisplay(
  toolName: string,
  args?: Record<string, unknown>,
): { label: string; detail: string } {
  const label = toolName
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())

  let detail = ''
  if (args && Object.keys(args).length > 0) {
    const preview = JSON.stringify(args).slice(0, 100)
    detail = preview.length < JSON.stringify(args).length ? `${preview}...` : preview
  }

  return { label, detail }
}
