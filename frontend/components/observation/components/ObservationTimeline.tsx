'use client'

import { useMemo, useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { flattenTreeWithTimelineMetrics } from '../lib/timeline-flattening'
import { calculateStepSize, SCALE_WIDTH } from '../lib/timeline-calculations'
import { useObservationData } from '../contexts/ObservationDataContext'
import { useObservationSelection } from '../contexts/ObservationSelectionContext'
import { useObservationViewPrefs } from '../contexts/ObservationViewPrefsContext'
import { ObservationNodeWrapper } from './ObservationNodeWrapper'
import { TimelineBar } from './TimelineBar'
import { TimelineScale } from './TimelineScale'

export function ObservationTimeline() {
  const { roots } = useObservationData()
  const { selectedNodeId, selectNode, collapsedNodes, toggleCollapse } = useObservationSelection()
  const { showCostTokens, colorCodeMetrics } = useObservationViewPrefs()

  const scrollRef = useRef<HTMLDivElement>(null)
  const timeIndexRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)

  const traceDuration = useMemo(() => Math.max(...roots.map((r) => r.latency ?? 0), 0.01), [roots])
  const traceStartTime = useMemo(
    () =>
      roots.length > 0
        ? new Date(Math.min(...roots.map((r) => r.startTime.getTime())))
        : new Date(),
    [roots],
  )
  const stepSize = useMemo(() => calculateStepSize(traceDuration), [traceDuration])

  const flatItems = useMemo(
    () =>
      flattenTreeWithTimelineMetrics(
        roots,
        collapsedNodes,
        traceStartTime,
        traceDuration,
        SCALE_WIDTH,
      ),
    [roots, collapsedNodes, traceStartTime, traceDuration],
  )

  const rowVirtualizer = useVirtualizer({
    count: flatItems.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 42,
    overscan: 500,
  })

  const rootTotalCost = roots.length > 0 ? roots[0].totalCost : undefined

  const handleTimeIndexScroll = (e: React.UIEvent<HTMLDivElement>) => {
    if (contentRef.current) contentRef.current.scrollLeft = e.currentTarget.scrollLeft
  }
  const handleContentScroll = (e: React.UIEvent<HTMLDivElement>) => {
    if (timeIndexRef.current) timeIndexRef.current.scrollLeft = e.currentTarget.scrollLeft
  }

  return (
    <div className="flex h-full flex-col">
      <div ref={timeIndexRef} className="shrink-0 overflow-x-auto" onScroll={handleTimeIndexScroll}>
        <TimelineScale traceDuration={traceDuration} scaleWidth={SCALE_WIDTH} stepSize={stepSize} />
      </div>

      <div ref={scrollRef} className="flex-1 overflow-auto" onScroll={handleContentScroll}>
        <div
          ref={contentRef}
          style={{
            height: `${rowVirtualizer.getTotalSize()}px`,
            width: `${SCALE_WIDTH + 200}px`,
          }}
          className="relative"
        >
          {rowVirtualizer.getVirtualItems().map((virtualItem) => {
            const item = flatItems[virtualItem.index]
            const isSelected = item.node.id === selectedNodeId

            return (
              <div
                key={item.node.id}
                className="absolute left-0 top-0 flex w-full items-center"
                style={{
                  height: `${virtualItem.size}px`,
                  transform: `translateY(${virtualItem.start}px)`,
                }}
              >
                <div className="w-[200px] shrink-0">
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
                    <span className="truncate text-xs">{item.node.name}</span>
                  </ObservationNodeWrapper>
                </div>
                <div className="flex-1">
                  <TimelineBar
                    node={item.node}
                    metrics={item.metrics}
                    isSelected={isSelected}
                    onSelect={() => selectNode(item.node.id)}
                    showCostTokens={showCostTokens}
                    colorCodeMetrics={colorCodeMetrics}
                    parentTotalCost={rootTotalCost}
                  />
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
