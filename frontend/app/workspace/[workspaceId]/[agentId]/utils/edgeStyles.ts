/**
 * Edge Style Utilities
 *
 * Centralized edge styling logic. All edge type → style/ReactFlow-type mappings
 * should go through these utilities to avoid duplication.
 */

import type { CSSProperties } from 'react'
import type { Edge } from 'reactflow'

import type { EdgeData } from '../types/graph'

// ── Edge Style Constants ────────────────────────────────────────────

export const EDGE_COLORS = {
    normal: '#cbd5e1',      // gray-300
    conditional: '#3b82f6', // blue-500
    loop_back: '#9333ea',   // violet-600
} as const

// ── Core Helper ─────────────────────────────────────────────────────

/**
 * Get the ReactFlow edge type and CSS style for a given edge_type.
 *
 * This is the single source of truth for edge appearance.
 */
export function getEdgeStyleByType(
    edgeType: EdgeData['edge_type'] | undefined,
    baseStyle?: CSSProperties
): { type: string; style: CSSProperties } {
    const base = baseStyle || {}

    if (edgeType === 'loop_back') {
        return {
            type: 'loop_back',
            style: {
                ...base,
                stroke: EDGE_COLORS.loop_back,
                strokeWidth: 2.5,
                strokeDasharray: '8,4',
            },
        }
    }

    if (edgeType === 'conditional') {
        return {
            type: 'default',
            style: {
                ...base,
                stroke: EDGE_COLORS.conditional,
                strokeWidth: 2,
            },
        }
    }

    // Normal edge
    return {
        type: 'default',
        style: {
            ...base,
            stroke: (base as any).stroke || EDGE_COLORS.normal,
            strokeWidth: (base as any).strokeWidth || 1.5,
        },
    }
}

// ── Edge Processing ─────────────────────────────────────────────────

/**
 * Process edges loaded from backend to ensure correct ReactFlow type and style.
 *
 * Used by both loadGraph branches and importGraph to avoid duplicating
 * the edge_type → type/style mapping logic.
 */
export function processEdgesForReactFlow(edges: Edge[]): Edge[] {
    return edges.map((edge) => {
        const edgeData = (edge.data || {}) as EdgeData
        const { type, style } = getEdgeStyleByType(edgeData.edge_type, edge.style)
        return { ...edge, type, style }
    })
}
