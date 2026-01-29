'use client'

import React, { useMemo } from 'react'
import { BaseEdge, EdgeProps, getBezierPath, EdgeLabelRenderer } from 'reactflow'

import { EdgeData } from '../types/graph'

/**
 * DefaultEdge - Custom edge component for normal and conditional edges
 *
 * Features:
 * - Supports label display on the edge line
 * - Different colors for conditional vs normal edges
 * - Label positioned above the edge line
 */
export const DefaultEdge: React.FC<EdgeProps> = ({
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
}) => {
  const edgeData = (data || {}) as EdgeData

  // Calculate edge path and label position
  const { edgePath, labelX, labelY } = useMemo(() => {
    const [path, labelX, labelY] = getBezierPath({
      sourceX,
      sourceY,
      sourcePosition,
      targetX,
      targetY,
      targetPosition,
    })

    return { edgePath: path, labelX, labelY }
  }, [sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition])

  // Determine edge style based on edge_type
  const edgeStyle = useMemo(() => {
    if (edgeData.edge_type === 'conditional') {
      return {
        ...style,
        stroke: '#3b82f6', // blue-500
        strokeWidth: 2,
      }
    }
    // Normal edge
    return {
      ...style,
      stroke: '#cbd5e1', // gray-300
      strokeWidth: 1.5,
    }
  }, [style, edgeData.edge_type])

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={edgeStyle}
        markerEnd={markerEnd}
      />
      {/* Edge label if available - positioned at the middle of the edge line */}
      {edgeData.label && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              fontSize: 10,
              pointerEvents: 'all',
            }}
            className="nodrag nopan bg-white border border-gray-300 text-gray-700 px-2 py-0.5 rounded shadow-sm font-medium"
          >
            {edgeData.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}
