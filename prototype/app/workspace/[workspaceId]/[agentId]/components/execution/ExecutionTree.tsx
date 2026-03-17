'use client'

/**
 * ExecutionTree - Hierarchical tree view for execution steps.
 *
 * Features:
 * - Virtualized rendering via @tanstack/react-virtual
 * - Expand/collapse nodes
 * - Tree connector lines and indentation
 * - Auto-scroll to latest node during execution
 * - Search filtering with highlight
 *
 * Inspired by langfuse TraceTree.tsx + VirtualizedTree.tsx
 */

import { ChevronRight, PlayCircle } from 'lucide-react'
import React, { useRef, useEffect, useCallback, useMemo } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'

import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'

import { useExecutionData } from './contexts/ExecutionDataContext'
import { useExecutionSelection } from './contexts/ExecutionSelectionContext'
import { ExecutionTreeNodeContent } from './ExecutionTreeNodeContent'

const TREE_INDENT_PX = 20
const ROW_HEIGHT = 36

interface ExecutionTreeProps {
  searchQuery?: string
}

export const ExecutionTree: React.FC<ExecutionTreeProps> = ({ searchQuery = '' }) => {
  const { t } = useTranslation()
  const { flatItems, isExecuting } = useExecutionData()
  const { selectedNodeId, selectNode, toggleCollapse } = useExecutionSelection()
  const parentRef = useRef<HTMLDivElement>(null)
  const shouldAutoScrollRef = useRef(true)

  // Filter items by search query
  const filteredItems = useMemo(() => {
    if (!searchQuery.trim()) return flatItems

    const query = searchQuery.toLowerCase()
    return flatItems.filter(item => {
      const name = item.node.name?.toLowerCase() || ''
      const stepType = item.node.step?.stepType?.toLowerCase() || ''
      const content = item.node.step?.content?.toLowerCase() || ''
      return name.includes(query) || stepType.includes(query) || content.includes(query)
    })
  }, [flatItems, searchQuery])

  const virtualizer = useVirtualizer({
    count: filteredItems.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 10,
  })

  // Auto-scroll when new items are added during execution
  useEffect(() => {
    if (isExecuting && filteredItems.length > 0 && shouldAutoScrollRef.current && !searchQuery) {
      virtualizer.scrollToIndex(filteredItems.length - 1, { align: 'end' })
    }
  }, [filteredItems.length, isExecuting, virtualizer, searchQuery])

  // Handle manual scroll to disable auto-scroll
  const handleScroll = useCallback(() => {
    if (!parentRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = parentRef.current
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 80
    shouldAutoScrollRef.current = isNearBottom
  }, [])

  if (flatItems.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-3 opacity-60">
        <div className="w-12 h-12 rounded-full border border-gray-100 bg-gray-50 flex items-center justify-center">
          <PlayCircle size={20} strokeWidth={1} />
        </div>
        <span className="text-xs font-medium font-mono">
          {t('workspace.readyToExecute', { defaultValue: 'Ready to execute' })}
        </span>
      </div>
    )
  }

  if (searchQuery && filteredItems.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-2">
        <span className="text-xs font-mono">No results for &quot;{searchQuery}&quot;</span>
      </div>
    )
  }

  return (
    <div
      ref={parentRef}
      onScroll={handleScroll}
      className="flex-1 overflow-auto h-full"
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
          const item = filteredItems[virtualRow.index]
          if (!item) return null

          const { node, isExpanded, hasChildren } = item
          const depth = node.depth
          const isSelected = selectedNodeId === node.id

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
              }}
            >
              <div
                className="flex items-center relative"
                style={{ paddingLeft: `${depth * TREE_INDENT_PX + 4}px` }}
              >
                {/* Connector lines */}
                {depth > 0 && !searchQuery && (
                  <>
                    {Array.from({ length: depth }, (_, i) => (
                      <div
                        key={i}
                        className="absolute top-0 bottom-0 w-px bg-gray-200"
                        style={{ left: `${(i + 1) * TREE_INDENT_PX - 4}px` }}
                      />
                    ))}
                    {/* Horizontal connector */}
                    <div
                      className="absolute h-px bg-gray-200"
                      style={{
                        left: `${depth * TREE_INDENT_PX - 4}px`,
                        width: '8px',
                        top: '50%',
                      }}
                    />
                  </>
                )}

                {/* Expand/collapse button */}
                <div className="w-5 h-5 flex items-center justify-center shrink-0 relative z-10">
                  {hasChildren && !searchQuery ? (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        toggleCollapse(node.id)
                      }}
                      className="p-0.5 rounded hover:bg-gray-200 transition-colors"
                    >
                      <ChevronRight
                        size={12}
                        className={cn(
                          'text-gray-400 transition-transform duration-150',
                          isExpanded && 'rotate-90'
                        )}
                      />
                    </button>
                  ) : (
                    <div className="w-3" />
                  )}
                </div>

                {/* Node content */}
                <div className="flex-1 min-w-0">
                  <ExecutionTreeNodeContent
                    node={node}
                    isSelected={isSelected}
                    onClick={() => selectNode(node.id)}
                  />
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Waiting indicator */}
      {isExecuting && !searchQuery && (
        <div className="px-4 py-2 flex items-center gap-2">
          <div className="w-1 h-3 bg-cyan-400 animate-pulse" />
          <span className="text-[9px] text-cyan-600 font-mono animate-pulse">
            {t('workspace.waitingForNextStep', { defaultValue: 'Waiting for next step...' })}
          </span>
        </div>
      )}
    </div>
  )
}
