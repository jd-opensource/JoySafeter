'use client'

/**
 * ExecutionTimeline - Gantt-chart style timeline view for execution steps.
 *
 * Features:
 * - Horizontal time bars showing duration and concurrency
 * - Node name + tree indentation on the left
 * - Time scale header
 * - Virtualized rendering
 *
 * Inspired by langfuse TraceTimeline/
 */

import { useVirtualizer } from '@tanstack/react-virtual'
import { useRef, useMemo, useEffect } from 'react'

import { cn } from '@/lib/utils'

import { getTraceDuration } from '../../lib/tree-building'

import { useExecutionData } from './contexts/ExecutionDataContext'
import { useExecutionSelection } from './contexts/ExecutionSelectionContext'

const ROW_HEIGHT = 32
const NAME_WIDTH = 180
const MIN_BAR_WIDTH = 4

function getBarColor(status: string, stepType?: string): string {
  if (status === 'running') return 'bg-cyan-400'
  if (status === 'error') return 'bg-red-400'

  switch (stepType) {
    case 'node_lifecycle':
      return 'bg-primary'
    case 'tool_execution':
      return 'bg-amber-400'
    case 'model_io':
      return 'bg-indigo-400'
    case 'agent_thought':
      return 'bg-purple-400'
    case 'code_agent_code':
      return 'bg-primary'
    case 'code_agent_thought':
      return 'bg-indigo-400'
    case 'code_agent_observation':
      return 'bg-teal-400'
    default:
      return 'bg-[var(--text-muted)]'
  }
}

function formatTimeLabel(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
}

export function ExecutionTimelineView() {
  const { flatItems, treeRoots, isExecuting } = useExecutionData()
  const { selectedNodeId, selectNode } = useExecutionSelection()
  const parentRef = useRef<HTMLDivElement>(null)

  const traceDuration = useMemo(() => {
    const d = getTraceDuration(treeRoots)
    return Math.max(d, 100) // Minimum 100ms for rendering
  }, [treeRoots])

  const traceStart = useMemo(() => (treeRoots.length > 0 ? treeRoots[0].startTime : 0), [treeRoots])

  const virtualizer = useVirtualizer({
    count: flatItems.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
  })

  // Auto-scroll during execution
  useEffect(() => {
    if (isExecuting && flatItems.length > 0) {
      virtualizer.scrollToIndex(flatItems.length - 1, { align: 'end' })
    }
  }, [flatItems.length, isExecuting, virtualizer])

  // Generate time scale ticks
  const ticks = useMemo(() => {
    const tickCount = 5
    const step = traceDuration / tickCount
    return Array.from({ length: tickCount + 1 }, (_, i) => ({
      ms: i * step,
      percent: ((i * step) / traceDuration) * 100,
    }))
  }, [traceDuration])

  if (flatItems.length === 0) return null

  return (
    <div className="flex h-full flex-col">
      {/* Time Scale Header */}
      <div className="flex h-6 shrink-0 select-none border-b border-[var(--border)] bg-[var(--surface-2)]">
        <div className="shrink-0 border-r border-[var(--border)]" style={{ width: NAME_WIDTH }} />
        <div className="relative flex-1">
          {ticks.map((tick, i) => (
            <div
              key={i}
              className="absolute bottom-0 top-0 flex flex-col items-center"
              style={{ left: `${tick.percent}%` }}
            >
              <div className="h-2 w-px bg-[var(--text-subtle)]" />
              <span className="mt-0.5 font-mono text-xxs text-[var(--text-muted)]">
                {formatTimeLabel(tick.ms)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Timeline Rows */}
      <div ref={parentRef} className="flex-1 overflow-auto" style={{ contain: 'strict' }}>
        <div
          style={{
            height: `${virtualizer.getTotalSize()}px`,
            width: '100%',
            position: 'relative',
          }}
        >
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const item = flatItems[virtualRow.index]
            if (!item) return null

            const { node } = item
            const isSelected = selectedNodeId === node.id
            const nodeStart = node.startTime - traceStart
            const nodeDuration = node.endTime ? node.endTime - node.startTime : node.duration || 0

            const leftPercent = (nodeStart / traceDuration) * 100
            const widthPercent = Math.max(
              (nodeDuration / traceDuration) * 100,
              (MIN_BAR_WIDTH / (parentRef.current?.clientWidth || 800 - NAME_WIDTH)) * 100,
            )

            return (
              <div
                key={node.id}
                data-index={virtualRow.index}
                ref={virtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualRow.start}px)`,
                  height: ROW_HEIGHT,
                }}
                className={cn(
                  'flex cursor-pointer items-center border-b border-[var(--border-muted)] transition-colors',
                  isSelected ? 'bg-primary/5' : 'hover:bg-[var(--surface-2)]',
                )}
                onClick={() => selectNode(node.id)}
              >
                {/* Name column */}
                <div
                  className="flex min-w-0 shrink-0 items-center border-r border-[var(--border)] px-2"
                  style={{
                    width: NAME_WIDTH,
                    paddingLeft: `${node.depth * 16 + 8}px`,
                  }}
                >
                  <span className="truncate text-2xs font-medium text-[var(--text-secondary)]">
                    {node.name}
                  </span>
                </div>

                {/* Timeline bar */}
                <div className="relative h-full flex-1">
                  <div
                    className={cn(
                      'absolute top-1/2 h-4 -translate-y-1/2 rounded-sm transition-all',
                      getBarColor(node.status, node.step?.stepType),
                      node.status === 'running' && 'animate-pulse',
                      isSelected && 'ring-1 ring-primary',
                    )}
                    style={{
                      left: `${leftPercent}%`,
                      width: `${widthPercent}%`,
                      minWidth: `${MIN_BAR_WIDTH}px`,
                    }}
                  >
                    {nodeDuration > 0 && widthPercent > 5 && (
                      <span className="absolute inset-0 flex items-center justify-center truncate px-1 font-mono text-xxs font-medium text-white">
                        {formatTimeLabel(nodeDuration)}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
