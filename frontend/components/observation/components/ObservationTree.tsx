'use client'

import { useEffect, useLayoutEffect, useMemo, useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { flattenTree } from '../lib/tree-flattening'
import { useObservationData } from '../contexts/ObservationDataContext'
import { useObservationSelection } from '../contexts/ObservationSelectionContext'
import { ObservationNodeWrapper } from './ObservationNodeWrapper'
import { ObservationSpanContent } from './ObservationSpanContent'

export function ObservationTree() {
  const { roots, isExecuting } = useObservationData()
  const { selectedNodeId, selectNode, collapsedNodes, toggleCollapse } = useObservationSelection()

  const scrollRef = useRef<HTMLDivElement>(null)

  const flatItems = useMemo(() => flattenTree(roots, collapsedNodes), [roots, collapsedNodes])

  const rowVirtualizer = useVirtualizer({
    count: flatItems.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 37,
    overscan: 500,
    measureElement: (el) => el.getBoundingClientRect().height,
  })

  const initialNodeIdRef = useRef(selectedNodeId)
  const hasScrolledRef = useRef(false)

  useLayoutEffect(() => {
    if (selectedNodeId && !hasScrolledRef.current && selectedNodeId === initialNodeIdRef.current) {
      const index = flatItems.findIndex((item) => item.node.id === selectedNodeId)
      if (index !== -1) {
        rowVirtualizer.scrollToIndex(index, {
          align: 'center',
          behavior: 'auto',
        })
        hasScrolledRef.current = true
      }
    }
  }, [selectedNodeId, flatItems, rowVirtualizer])

  useEffect(() => {
    if (isExecuting && flatItems.length > 0) {
      rowVirtualizer.scrollToIndex(flatItems.length - 1, { align: 'end' })
    }
  }, [isExecuting, flatItems.length, rowVirtualizer])

  const rootTotalCost = roots.length > 0 ? roots[0].totalCost : undefined
  const rootTotalDuration = roots.length > 0 ? (roots[0].latency ?? undefined) : undefined

  return (
    <div ref={scrollRef} className="h-full overflow-auto">
      <div style={{ height: `${rowVirtualizer.getTotalSize()}px` }} className="relative w-full">
        {rowVirtualizer.getVirtualItems().map((virtualItem) => {
          const item = flatItems[virtualItem.index]
          const isSelected = item.node.id === selectedNodeId

          return (
            <div
              key={item.node.id}
              ref={rowVirtualizer.measureElement}
              data-index={virtualItem.index}
              className="absolute left-0 top-0 w-full"
              style={{
                transform: `translateY(${virtualItem.start}px)`,
              }}
            >
              <ObservationNodeWrapper
                metadata={item}
                nodeType={item.node.type}
                hasChildren={item.node.children.length > 0}
                isCollapsed={collapsedNodes.has(item.node.id)}
                onToggleCollapse={() => toggleCollapse(item.node.id)}
                isSelected={isSelected}
                onSelect={() => selectNode(item.node.id)}
                isError={item.node.level === 'ERROR'}
              >
                <ObservationSpanContent
                  node={item.node}
                  parentTotalCost={rootTotalCost}
                  parentTotalDuration={rootTotalDuration}
                />
              </ObservationNodeWrapper>
            </div>
          )
        })}
      </div>
    </div>
  )
}
