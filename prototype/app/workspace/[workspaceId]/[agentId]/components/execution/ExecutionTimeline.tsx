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

import React, { useRef, useMemo, useCallback, useEffect } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'

import { cn } from '@/lib/core/utils/cn'
import type { ExecutionTreeFlatItem } from '@/types'

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
    case 'node_lifecycle': return 'bg-blue-400'
    case 'tool_execution': return 'bg-amber-400'
    case 'model_io': return 'bg-indigo-400'
    case 'agent_thought': return 'bg-purple-400'
    case 'code_agent_code': return 'bg-blue-500'
    case 'code_agent_thought': return 'bg-indigo-400'
    case 'code_agent_observation': return 'bg-teal-400'
    default: return 'bg-gray-400'
  }
}

function formatTimeLabel(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
}

export const ExecutionTimelineView: React.FC = () => {
  const { flatItems, treeRoots, isExecuting } = useExecutionData()
  const { selectedNodeId, selectNode } = useExecutionSelection()
  const parentRef = useRef<HTMLDivElement>(null)

  const traceDuration = useMemo(() => {
    const d = getTraceDuration(treeRoots)
    return Math.max(d, 100) // Minimum 100ms for rendering
  }, [treeRoots])

  const traceStart = useMemo(
    () => (treeRoots.length > 0 ? treeRoots[0].startTime : 0),
    [treeRoots]
  )

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
      percent: (i * step / traceDuration) * 100,
    }))
  }, [traceDuration])

  if (flatItems.length === 0) return null

  return (
    <div className="h-full flex flex-col">
      {/* Time Scale Header */}
      <div className="h-6 border-b border-gray-200 flex shrink-0 bg-gray-50/80 select-none">
        <div className="shrink-0 border-r border-gray-200" style={{ width: NAME_WIDTH }} />
        <div className="flex-1 relative">
          {ticks.map((tick, i) => (
            <div
              key={i}
              className="absolute top-0 bottom-0 flex flex-col items-center"
              style={{ left: `${tick.percent}%` }}
            >
              <div className="w-px h-2 bg-gray-300" />
              <span className="text-[8px] text-gray-400 font-mono mt-0.5">
                {formatTimeLabel(tick.ms)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Timeline Rows */}
      <div
        ref={parentRef}
        className="flex-1 overflow-auto"
        style={{ contain: 'strict' }}
      >
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
            const nodeDuration = node.endTime
              ? node.endTime - node.startTime
              : node.duration || 0

            const leftPercent = (nodeStart / traceDuration) * 100
            const widthPercent = Math.max(
              (nodeDuration / traceDuration) * 100,
              (MIN_BAR_WIDTH / (parentRef.current?.clientWidth || 800 - NAME_WIDTH)) * 100
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
                  'flex items-center cursor-pointer border-b border-gray-100 transition-colors',
                  isSelected ? 'bg-blue-50' : 'hover:bg-gray-50'
                )}
                onClick={() => selectNode(node.id)}
              >
                {/* Name column */}
                <div
                  className="shrink-0 border-r border-gray-200 px-2 flex items-center min-w-0"
                  style={{
                    width: NAME_WIDTH,
                    paddingLeft: `${node.depth * 16 + 8}px`,
                  }}
                >
                  <span className="text-[10px] text-gray-600 font-medium truncate">
                    {node.name}
                  </span>
                </div>

                {/* Timeline bar */}
                <div className="flex-1 relative h-full">
                  <div
                    className={cn(
                      'absolute top-1/2 -translate-y-1/2 h-4 rounded-sm transition-all',
                      getBarColor(node.status, node.step?.stepType),
                      node.status === 'running' && 'animate-pulse',
                      isSelected && 'ring-1 ring-blue-400'
                    )}
                    style={{
                      left: `${leftPercent}%`,
                      width: `${widthPercent}%`,
                      minWidth: `${MIN_BAR_WIDTH}px`,
                    }}
                  >
                    {nodeDuration > 0 && widthPercent > 5 && (
                      <span className="absolute inset-0 flex items-center justify-center text-[8px] text-white font-mono font-medium truncate px-1">
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
