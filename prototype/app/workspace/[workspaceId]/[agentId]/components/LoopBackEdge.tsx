'use client'

import { GripHorizontal, GripVertical } from 'lucide-react'
import React, { useCallback, useState, useMemo, useEffect, useRef } from 'react'
import { BaseEdge, EdgeProps, EdgeLabelRenderer } from 'reactflow'

import { cn } from '@/lib/core/utils/cn'

import { useBuilderStore } from '../stores/builderStore'
import { EdgeData } from '../types/graph'


/**
 * LoopBackEdge - Custom edge component for loop back connections with Manhattan Routing
 *
 * Features:
 * - Orthogonal path (Manhattan Routing) with only horizontal/vertical segments
 * - Three draggable handles: vertical channel (Y offset), left/right segments (X offsets)
 * - Distinctive purple/violet color to differentiate from other edges
 * - Elegant thin dashed line style with rounded caps
 * - Handles only visible when edge is selected
 * - Supports both true loopback (source == target) and backward connections
 *
 * Implementation:
 * - Uses offsetY for vertical channel position
 * - Uses leftOffsetX and rightOffsetX for horizontal segment positions
 * - Automatically calculates default path if offsets are not set
 * - Optimized with useMemo for path calculation and style
 *
 * Based on reference implementation with improvements for current project architecture
 */

// Custom Orthogonal Path Generator for Loopback Edges
const getSmartOrthogonalPath = (
  sourceX: number,
  sourceY: number,
  targetX: number,
  targetY: number,
  offsetY: number = 0,
  leftOffsetX: number = 0,
  rightOffsetX: number = 0
): [string, number, number, number, number, number, number] => {
  // Is this a backward loop? (Target is to the left of Source)
  const isLoopback = targetX < sourceX + 50

  let d = ''
  let labelX = 0
  let labelY = 0
  let leftX = 0
  let rightX = 0
  let leftY = 0 // Y position for left handle
  let rightY = 0 // Y position for right handle

  if (isLoopback) {
    // LOOPBACK LOGIC
    // 1. Start right
    // 2. Go Up/Down to channel
    // 3. Go Left past target
    // 4. Go Up/Down to target Y
    // 5. Go Right to target

    const channelY = offsetY !== 0 ? offsetY : Math.min(sourceY, targetY) - 60

    // Calculate right and left limits with offsets
    const defaultRightLimit = Math.max(sourceX, targetX) + 60
    const defaultLeftLimit = Math.min(sourceX, targetX) - 60

    const rightLimit = rightOffsetX !== 0 ? rightOffsetX : defaultRightLimit
    const leftLimit = leftOffsetX !== 0 ? leftOffsetX : defaultLeftLimit

    d = `M ${sourceX} ${sourceY} L ${rightLimit} ${sourceY} L ${rightLimit} ${channelY} L ${leftLimit} ${channelY} L ${leftLimit} ${targetY} L ${targetX} ${targetY}`

    labelX = (rightLimit + leftLimit) / 2
    labelY = channelY
    leftX = leftLimit
    rightX = rightLimit
    // Left handle is on the left vertical segment (between sourceY and channelY)
    leftY = (sourceY + channelY) / 2
    // Right handle is on the right vertical segment (between sourceY and channelY)
    rightY = (sourceY + channelY) / 2

  } else {
    // STANDARD STEP LOGIC with Draggable Vertical Segment
    // 1. Start right
    // 2. Go to channel Y
    // 3. Go right
    // 4. Go to target Y
    // 5. Target

    // Default channel is just the midpoint Y if not dragged
    const channelY = offsetY !== 0 ? offsetY : (sourceY + targetY) / 2

    const defaultStartStub = sourceX + 30
    const defaultEndStub = targetX - 30

    const startStub = leftOffsetX !== 0 ? leftOffsetX : defaultStartStub
    const endStub = rightOffsetX !== 0 ? rightOffsetX : defaultEndStub

    d = `M ${sourceX} ${sourceY} L ${startStub} ${sourceY} L ${startStub} ${channelY} L ${endStub} ${channelY} L ${endStub} ${targetY} L ${targetX} ${targetY}`

    labelX = (startStub + endStub) / 2
    labelY = channelY
    leftX = startStub
    rightX = endStub
    // Left handle is on the left vertical segment (between sourceY and channelY)
    leftY = (sourceY + channelY) / 2
    // Right handle is on the right vertical segment (between targetY and channelY)
    rightY = (targetY + channelY) / 2
  }

  return [d, labelX, labelY, leftX, rightX, leftY, rightY]
}

export const LoopBackEdge: React.FC<EdgeProps> = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
  data,
  selected,
}) => {
  const edgeData = (data || {}) as EdgeData
  const selectedEdgeId = useBuilderStore((state) => state.selectedEdgeId)
  const updateEdge = useBuilderStore((state) => state.updateEdge)
  const takeSnapshot = useBuilderStore((state) => state.takeSnapshot)
  const rfInstance = useBuilderStore((state) => state.rfInstance)

  const isSelected = selected || selectedEdgeId === id
  const [draggingHandle, setDraggingHandle] = useState<'vertical' | 'left' | 'right' | null>(null)

  // Track active event listeners for cleanup on unmount
  const activeListenersRef = useRef<{
    onMouseMove?: (e: MouseEvent | TouchEvent) => void
    onMouseUp?: () => void
  }>({})

  // Get stored offsets or 0. 0 means "calculate default"
  const currentOffsetY = edgeData.offsetY || 0
  const currentLeftOffsetX = edgeData.leftOffsetX || 0
  const currentRightOffsetX = edgeData.rightOffsetX || 0

  // Memoize path calculation to avoid unnecessary recalculations
  const pathData = useMemo(() => {
    return getSmartOrthogonalPath(
      sourceX,
      sourceY,
      targetX,
      targetY,
      currentOffsetY,
      currentLeftOffsetX,
      currentRightOffsetX
    )
  }, [sourceX, sourceY, targetX, targetY, currentOffsetY, currentLeftOffsetX, currentRightOffsetX])

  const [path, labelX, labelY, leftX, rightX, leftY, rightY] = pathData

  const onEdgeClick = useCallback((evt: React.MouseEvent<HTMLDivElement, MouseEvent>) => {
    evt.stopPropagation()
  }, [])

  // Generic drag handler factory to reduce code duplication
  const createDragHandler = useCallback((
    handleType: 'vertical' | 'left' | 'right',
    getInitialValue: () => number,
    updateData: (value: number) => Partial<EdgeData>
  ) => {
    return (event: React.MouseEvent | React.TouchEvent) => {
      event.stopPropagation()
      setDraggingHandle(handleType)
      takeSnapshot()

      const isTouch = 'touches' in event
      const startPos = isTouch
        ? (handleType === 'vertical' ? event.touches[0].clientY : event.touches[0].clientX)
        : (handleType === 'vertical' ? event.clientY : event.clientX)
      const initialValue = getInitialValue()

      const onMouseMove = (moveEvent: MouseEvent | TouchEvent) => {
        const isTouchMove = 'touches' in moveEvent
        const currentPos = isTouchMove
          ? (handleType === 'vertical' ? moveEvent.touches[0].clientY : moveEvent.touches[0].clientX)
          : (handleType === 'vertical' ? moveEvent.clientY : moveEvent.clientX)

        const viewportZoom = rfInstance?.getViewport().zoom || 1
        const delta = (currentPos - startPos) / viewportZoom

        updateEdge(id, updateData(initialValue + delta))
      }

      const onMouseUp = () => {
        setDraggingHandle(null)
        window.removeEventListener('mousemove', onMouseMove)
        window.removeEventListener('mouseup', onMouseUp)
        window.removeEventListener('touchmove', onMouseMove)
        window.removeEventListener('touchend', onMouseUp)
        // Clear ref
        activeListenersRef.current = {}
      }

      // Store listeners in ref for cleanup
      activeListenersRef.current = { onMouseMove, onMouseUp }

      window.addEventListener('mousemove', onMouseMove)
      window.addEventListener('mouseup', onMouseUp)
      window.addEventListener('touchmove', onMouseMove)
      window.addEventListener('touchend', onMouseUp)
    }
  }, [takeSnapshot, rfInstance, updateEdge, id])

  // Handle vertical drag (horizontal channel)
  const handleVerticalDragStart = useMemo(
    () => createDragHandler(
      'vertical',
      () => currentOffsetY !== 0 ? currentOffsetY : labelY,
      (value) => ({ offsetY: value })
    ),
    [createDragHandler, currentOffsetY, labelY]
  )

  // Handle left vertical segment drag
  const handleLeftDragStart = useMemo(
    () => createDragHandler(
      'left',
      () => currentLeftOffsetX !== 0 ? currentLeftOffsetX : leftX,
      (value) => ({ leftOffsetX: value })
    ),
    [createDragHandler, currentLeftOffsetX, leftX]
  )

  // Handle right vertical segment drag
  const handleRightDragStart = useMemo(
    () => createDragHandler(
      'right',
      () => currentRightOffsetX !== 0 ? currentRightOffsetX : rightX,
      (value) => ({ rightOffsetX: value })
    ),
    [createDragHandler, currentRightOffsetX, rightX]
  )

  // Cleanup event listeners on unmount
  useEffect(() => {
    return () => {
      const { onMouseMove, onMouseUp } = activeListenersRef.current
      if (onMouseMove) {
        window.removeEventListener('mousemove', onMouseMove)
        window.removeEventListener('touchmove', onMouseMove)
      }
      if (onMouseUp) {
        window.removeEventListener('mouseup', onMouseUp)
        window.removeEventListener('touchend', onMouseUp)
      }
      activeListenersRef.current = {}
    }
  }, [])

  // Distinctive purple/violet color for loop back edges - thinner and more elegant
  const loopBackStyle = useMemo(() => ({
    ...style,
    stroke: isSelected ? '#8b5cf6' : '#a78bfa', // violet-500, lighter and more elegant
    strokeWidth: isSelected ? 1.5 : 1.2, // Thinner lines
    strokeDasharray: '6,3', // Finer dashed pattern
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    filter: isSelected ? 'drop-shadow(0 0 2px rgba(139, 92, 246, 0.3))' : 'none',
  }), [style, isSelected])

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        style={loopBackStyle}
        markerEnd={markerEnd}
      />

      {/* Edge label if available */}
      {edgeData.label && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: 'all',
            }}
            className={cn(
              'nodrag nopan px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider border shadow-sm bg-white z-10',
              isSelected ? 'text-violet-600 border-violet-200' : 'text-violet-500 border-violet-200'
            )}
          >
            {edgeData.label}
          </div>
        </EdgeLabelRenderer>
      )}

      {/* Drag Handles - only visible when edge is selected */}
      {isSelected && (
        <EdgeLabelRenderer>
          {/* Horizontal channel drag handle (vertical movement) */}
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY + (edgeData.label ? 20 : 0)}px)`,
              pointerEvents: 'all',
            }}
            className="nodrag nopan cursor-row-resize group z-20"
            onMouseDown={handleVerticalDragStart}
            onTouchStart={handleVerticalDragStart}
            onClick={onEdgeClick}
          >
            <div className={cn(
              "bg-white border rounded-full p-1.5 shadow-md transition-all",
              draggingHandle === 'vertical'
                ? "bg-violet-100 border-violet-500 scale-110 shadow-lg"
                : "border-violet-300 hover:bg-violet-50 hover:border-violet-400 active:scale-95"
            )}>
              <GripHorizontal size={14} className={cn(
                draggingHandle === 'vertical' ? "text-violet-600" : "text-violet-400 group-hover:text-violet-500"
              )} />
            </div>
          </div>

          {/* Left vertical segment drag handle (horizontal movement) */}
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${leftX}px,${leftY}px)`,
              pointerEvents: 'all',
            }}
            className="nodrag nopan cursor-col-resize group z-20"
            onMouseDown={handleLeftDragStart}
            onTouchStart={handleLeftDragStart}
            onClick={onEdgeClick}
          >
            <div className={cn(
              "bg-white border rounded-full p-1.5 shadow-md transition-all",
              draggingHandle === 'left'
                ? "bg-violet-100 border-violet-500 scale-110 shadow-lg"
                : "border-violet-300 hover:bg-violet-50 hover:border-violet-400 active:scale-95"
            )}>
              <GripVertical size={14} className={cn(
                draggingHandle === 'left' ? "text-violet-600" : "text-violet-400 group-hover:text-violet-500"
              )} />
            </div>
          </div>

          {/* Right vertical segment drag handle (horizontal movement) */}
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${rightX}px,${rightY}px)`,
              pointerEvents: 'all',
            }}
            className="nodrag nopan cursor-col-resize group z-20"
            onMouseDown={handleRightDragStart}
            onTouchStart={handleRightDragStart}
            onClick={onEdgeClick}
          >
            <div className={cn(
              "bg-white border rounded-full p-1.5 shadow-md transition-all",
              draggingHandle === 'right'
                ? "bg-violet-100 border-violet-500 scale-110 shadow-lg"
                : "border-violet-300 hover:bg-violet-50 hover:border-violet-400 active:scale-95"
            )}>
              <GripVertical size={14} className={cn(
                draggingHandle === 'right' ? "text-violet-600" : "text-violet-400 group-hover:text-violet-500"
              )} />
            </div>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}
