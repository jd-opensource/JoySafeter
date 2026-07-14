'use client'

import { useState, useCallback } from 'react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { useTranslation } from '@/lib/i18n'
import { formatDuration } from '@/lib/managed/analytics/formatters'
import { OBSERVATION_TYPE_COLORS, CHART_COLORS } from './constants'
import type { ObservationNode } from '@/lib/managed/analytics/types'

interface ObservationWaterfallProps {
  nodes: ObservationNode[]
  totalDurationMs: number
  loading?: boolean
}

function getTypeColor(node: ObservationNode): string {
  if (node.level === 'ERROR') return CHART_COLORS[4]
  const idx = OBSERVATION_TYPE_COLORS[node.type] ?? 0
  return CHART_COLORS[idx]
}

function SkeletonRows() {
  return (
    <div className="space-y-2 py-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex items-center gap-2 px-2 py-1.5">
          <div className="h-5 w-20 animate-pulse rounded-full bg-muted" />
          <div className="h-4 w-32 animate-pulse rounded bg-muted" />
          <div className="ml-auto h-2 w-32 animate-pulse rounded-full bg-muted" />
          <div className="h-4 w-12 animate-pulse rounded bg-muted" />
        </div>
      ))}
    </div>
  )
}

function ObservationRow({
  node,
  totalDurationMs,
  depth,
}: {
  node: ObservationNode
  totalDurationMs: number
  depth: number
}) {
  const [expanded, setExpanded] = useState(true)
  const hasChildren = node.children.length > 0
  const color = getTypeColor(node)
  const widthPercent = totalDurationMs > 0
    ? Math.max((node.duration_ms / totalDurationMs) * 100, 1)
    : 0

  const ttftPercent =
    node.completion_start_time && node.start_time && totalDurationMs > 0
      ? ((new Date(node.completion_start_time).getTime() -
          new Date(node.start_time).getTime()) /
          totalDurationMs) *
        100
      : null

  const toggle = useCallback(() => {
    if (hasChildren) setExpanded((prev) => !prev)
  }, [hasChildren])

  return (
    <div
      className={cn(depth > 0 && 'border-l border-border pl-4')}
    >
      <div
        className={cn(
          'flex items-center gap-2 py-1.5 rounded px-2',
          hasChildren && 'cursor-pointer',
          'hover:bg-accent/30',
        )}
        onClick={toggle}
      >
        <div className="flex items-center gap-1.5 min-w-0 flex-1">
          {hasChildren && (
            <span className="text-xs text-muted-foreground w-4 shrink-0 select-none">
              {expanded ? '▾' : '▸'}
            </span>
          )}
          {!hasChildren && <span className="w-4 shrink-0" />}
          <Badge
            variant="outline"
            className="text-[10px] leading-tight shrink-0 px-1.5 py-0"
            style={{ borderColor: color, color }}
          >
            {node.type}
          </Badge>
          <span className="text-sm truncate">{node.name}</span>
          {node.model && (
            <span className="text-xs text-muted-foreground truncate">
              {node.model}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div className="w-32 h-2 bg-muted/30 rounded-full overflow-hidden relative">
            <div
              style={{
                width: `${widthPercent}%`,
                backgroundColor: color,
                opacity: 0.3,
              }}
              className="h-full rounded-full"
            />
            {ttftPercent !== null && (
              <div
                className="absolute top-0 h-full w-0.5"
                style={{
                  left: `${Math.min(ttftPercent, 100)}%`,
                  backgroundColor: color,
                }}
              />
            )}
          </div>
          <span className="text-xs tabular-nums text-muted-foreground w-16 text-right">
            {formatDuration(node.duration_ms)}
          </span>
          {node.cost > 0 && (
            <span className="text-xs text-muted-foreground w-14 text-right">
              ${node.cost.toFixed(3)}
            </span>
          )}
        </div>
      </div>
      {expanded && hasChildren && (
        <div>
          {node.children.map((child) => (
            <ObservationRow
              key={child.id}
              node={child}
              totalDurationMs={totalDurationMs}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export function ObservationWaterfall({
  nodes,
  totalDurationMs,
  loading = false,
}: ObservationWaterfallProps) {
  const { t } = useTranslation()

  if (loading) return <SkeletonRows />

  if (nodes.length === 0) {
    return (
      <div className="flex h-24 items-center justify-center">
        <p className="text-sm text-muted-foreground">{t('analytics.observations.noData')}</p>
      </div>
    )
  }

  return (
    <div className="space-y-0.5">
      {nodes.map((node) => (
        <ObservationRow
          key={node.id}
          node={node}
          totalDurationMs={totalDurationMs}
          depth={0}
        />
      ))}
    </div>
  )
}
